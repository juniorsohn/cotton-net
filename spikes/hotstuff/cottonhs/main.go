// Command cottonhs é o daemon de coordenação BFT do COTTON-NET (spike).
//
// Uma réplica relab/hotstuff por coordenador + API HTTP local:
//
//	POST /propose  corpo = NymLogEntry.encode() → bloqueia até f+1 réplicas executarem
//	               (substitui raft_node.propose() em coordinator/main.py)
//	GET  /status   {"applied", "hash", ...} — hash sha256 cumulativo da ordem de execução
//
// Cada comando comitado é entregue, em ordem, ao applier externo (POST applier_url),
// que no sistema real é o caminho FSM → _submit_nym do coordinator Python.
//
// Vive dentro do módulo relab porque precisa de internal/proto/clientpb.
// Depende do patch Config.OnExec em replica/ (ver ../../patches).
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"hash"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/relab/gorums"
	"github.com/relab/hotstuff"
	"github.com/relab/hotstuff/backend"
	"github.com/relab/hotstuff/blockchain"
	"github.com/relab/hotstuff/consensus"
	"github.com/relab/hotstuff/crypto"
	"github.com/relab/hotstuff/crypto/keygen"
	"github.com/relab/hotstuff/eventloop"
	"github.com/relab/hotstuff/internal/proto/clientpb"
	"github.com/relab/hotstuff/logging"
	"github.com/relab/hotstuff/modules"
	"github.com/relab/hotstuff/replica"
	"github.com/relab/hotstuff/synchronizer"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/protobuf/types/known/emptypb"

	// módulos registrados por nome
	_ "github.com/relab/hotstuff/consensus/chainedhotstuff"
	_ "github.com/relab/hotstuff/consensus/fasthotstuff"
	_ "github.com/relab/hotstuff/consensus/simplehotstuff"
	_ "github.com/relab/hotstuff/crypto/bls12"
	_ "github.com/relab/hotstuff/crypto/ecdsa"
	_ "github.com/relab/hotstuff/crypto/eddsa"
	_ "github.com/relab/hotstuff/leaderrotation"
)

type replicaEntry struct {
	ID          uint32 `json:"id"`
	ReplicaAddr string `json:"replica_addr"`
	ClientAddr  string `json:"client_addr"`
	HTTPAddr    string `json:"http_addr"`
	ApplierURL  string `json:"applier_url"`
}

type clusterConfig struct {
	Consensus      string         `json:"consensus"`
	Crypto         string         `json:"crypto"`
	LeaderRotation string         `json:"leader_rotation"`
	ViewTimeoutMs  float64        `json:"view_timeout_ms"`
	BatchSize      uint32         `json:"batch_size"`
	Replicas       []replicaEntry `json:"replicas"`
}

func keyPath(dir string, id hotstuff.ID, ext string) string {
	return filepath.Join(dir, fmt.Sprintf("r%d.%s", id, ext))
}

// ---------------------------------------------------------------- keygen

func runKeygen(args []string) error {
	fs := flag.NewFlagSet("keygen", flag.ExitOnError)
	n := fs.Int("n", 4, "número de réplicas (coordenadores)")
	dir := fs.String("dir", "cluster", "diretório de saída (chaves + cluster.json)")
	cryptoName := fs.String("crypto", "bls12", "ecdsa | bls12 | eddsa")
	consensusName := fs.String("consensus", "chainedhotstuff", "chainedhotstuff | fasthotstuff | simplehotstuff")
	host := fs.String("host", "127.0.0.1", "host de todas as réplicas (spike local)")
	basePort := fs.Int("base-port", 21000, "réplica=base+100+id, cliente=base+200+id, http=base+300+id, applier=base+400+id")
	_ = fs.Parse(args)

	if err := os.MkdirAll(*dir, 0o755); err != nil {
		return err
	}
	caKey, ca, err := keygen.GenerateCA()
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(*dir, "ca.crt"), keygen.CertToPEM(ca), 0o644); err != nil {
		return err
	}

	cfg := clusterConfig{
		Consensus:      *consensusName,
		Crypto:         *cryptoName,
		LeaderRotation: "round-robin",
		ViewTimeoutMs:  500,
		BatchSize:      1,
	}
	for i := 1; i <= *n; i++ {
		id := hotstuff.ID(i)
		kc, err := keygen.GenerateKeyChain(id, []string{*host, "localhost"}, *cryptoName, ca, caKey)
		if err != nil {
			return err
		}
		for ext, b := range map[string][]byte{"key": kc.PrivateKey, "pub": kc.PublicKey, "crt": kc.Certificate, "tlskey": kc.CertificateKey} {
			if err := os.WriteFile(keyPath(*dir, id, ext), b, 0o600); err != nil {
				return err
			}
		}
		addr := func(offset int) string { return net.JoinHostPort(*host, strconv.Itoa(*basePort+offset+i)) }
		cfg.Replicas = append(cfg.Replicas, replicaEntry{
			ID:          uint32(i),
			ReplicaAddr: addr(100),
			ClientAddr:  addr(200),
			HTTPAddr:    addr(300),
			ApplierURL:  "http://" + addr(400) + "/apply",
		})
	}
	b, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(*dir, "cluster.json"), b, 0o644)
}

// ---------------------------------------------------------------- réplica

type execItem struct {
	idx      uint64
	clientID uint32
	seq      uint64
	data     []byte
}

type daemon struct {
	id             hotstuff.ID
	self           replicaEntry
	rep            *replica.Replica
	cli            *clientpb.Configuration
	proposeTimeout time.Duration

	// sendMu serializa seq++ e ExecCommand: o cmdCache descarta comandos com seq
	// menor que o maior já proposto por cliente, então a ordem de envio importa.
	sendMu   sync.Mutex
	seq      uint64
	clientID uint32

	pending atomic.Int64  // comandos reais aguardando quórum de execução
	fillers atomic.Uint64 // no-ops enviados

	execMu  sync.Mutex
	applied uint64
	hash    hash.Hash

	applyCh chan execItem
}

// onExec roda no event loop do relab (hook Config.OnExec): não pode bloquear.
func (d *daemon) onExec(clientID uint32, seq uint64, data []byte) {
	if len(data) == 0 {
		return // no-op: só existe para avançar a 3-cadeia
	}
	d.execMu.Lock()
	d.applied++
	d.hash.Write(data)
	idx := d.applied
	d.execMu.Unlock()

	select {
	case d.applyCh <- execItem{idx: idx, clientID: clientID, seq: seq, data: append([]byte(nil), data...)}:
	default:
		log.Fatalf("applyCh cheio (idx=%d): applier não acompanha o commit", idx)
	}
}

// forwardLoop entrega os comandos ao applier em ordem, com retry (espelha pending.py).
func (d *daemon) forwardLoop() {
	httpc := &http.Client{Timeout: 5 * time.Second}
	for it := range d.applyCh {
		if d.self.ApplierURL == "" {
			continue
		}
		for attempt := 1; ; attempt++ {
			req, _ := http.NewRequest(http.MethodPost, d.self.ApplierURL, bytes.NewReader(it.data))
			req.Header.Set("X-Client-ID", strconv.FormatUint(uint64(it.clientID), 10))
			req.Header.Set("X-Seq", strconv.FormatUint(it.seq, 10))
			resp, err := httpc.Do(req)
			if err == nil {
				_, _ = io.Copy(io.Discard, resp.Body)
				resp.Body.Close()
				if resp.StatusCode < 300 {
					break
				}
				if resp.StatusCode < 500 {
					log.Printf("applier rejeitou idx=%d: status %d (descartado)", it.idx, resp.StatusCode)
					break
				}
				err = fmt.Errorf("status %d", resp.StatusCode)
			}
			backoff := min(time.Duration(attempt)*100*time.Millisecond, 2*time.Second)
			log.Printf("applier falhou idx=%d tentativa=%d: %v (retry em %v)", it.idx, attempt, err, backoff)
			time.Sleep(backoff)
		}
	}
}

func (d *daemon) submit(ctx context.Context, data []byte) *clientpb.AsyncEmpty {
	d.sendMu.Lock()
	defer d.sendMu.Unlock()
	d.seq++
	return d.cli.ExecCommand(ctx, &clientpb.Command{ClientID: d.clientID, SequenceNumber: d.seq, Data: data})
}

// fillerLoop: chained HotStuff só comita um bloco quando mais dois são construídos
// sobre ele (3-cadeia), o líder só propõe se houver comando (consensus.go Propose),
// e o cmdCache só libera lote com Len() > batchSize. Sem tráfego, a última NYM
// nunca comita. Enquanto houver comando real pendente, injeta no-ops (Data vazio),
// como o cliente de benchmark do relab faz ao chegar no EOF.
func (d *daemon) fillerLoop(interval time.Duration) {
	t := time.NewTicker(interval)
	defer t.Stop()
	for range t.C {
		if d.pending.Load() == 0 {
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), d.proposeTimeout)
		p := d.submit(ctx, nil)
		d.fillers.Add(1)
		go func() {
			_, _ = p.Get()
			cancel()
		}()
	}
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func (d *daemon) handlePropose(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "use POST", http.StatusMethodNotAllowed)
		return
	}
	data, err := io.ReadAll(r.Body)
	if err != nil || len(data) == 0 {
		http.Error(w, "corpo vazio", http.StatusBadRequest)
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), d.proposeTimeout)
	defer cancel()

	t0 := time.Now()
	d.pending.Add(1)
	_, err = d.submit(ctx, data).Get()
	d.pending.Add(-1)
	latencyMs := float64(time.Since(t0).Microseconds()) / 1000

	if err != nil {
		writeJSON(w, http.StatusGatewayTimeout, map[string]any{"ok": false, "error": err.Error(), "latency_ms": latencyMs})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "latency_ms": latencyMs})
}

func (d *daemon) handleStatus(w http.ResponseWriter, _ *http.Request) {
	d.execMu.Lock()
	applied, sum := d.applied, hex.EncodeToString(d.hash.Sum(nil))
	d.execMu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{
		"id":           d.id,
		"applied":      applied,
		"hash":         sum,
		"pending":      d.pending.Load(),
		"fillers_sent": d.fillers.Load(),
	})
}

type quorumSpec struct{ faulty int }

// ExecCommandQF: f+1 réplicas executaram ⇒ ao menos uma honesta comitou.
func (q *quorumSpec) ExecCommandQF(_ *clientpb.Command, replies map[uint32]*emptypb.Empty) (*emptypb.Empty, bool) {
	if len(replies) < q.faulty+1 {
		return nil, false
	}
	return &emptypb.Empty{}, true
}

// waitTCP espera o peer escutar: Connect abre streams e falha com peer ausente.
func waitTCP(addr string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for {
		c, err := net.DialTimeout("tcp", addr, time.Second)
		if err == nil {
			return c.Close()
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("peer %s não respondeu em %v: %w", addr, timeout, err)
		}
		time.Sleep(200 * time.Millisecond)
	}
}

func runReplica(args []string) error {
	fs := flag.NewFlagSet("replica", flag.ExitOnError)
	idFlag := fs.Uint("id", 0, "ID desta réplica (1..n)")
	dir := fs.String("dir", "cluster", "diretório gerado por `cottonhs keygen`")
	logLevel := fs.String("log-level", "info", "debug | info | warn | error")
	fillerInterval := fs.Duration("filler-interval", 0, "intervalo dos no-ops com comando pendente (0 = desliga; obsoleto desde -empty-blocks)")
	emptyBlocks := fs.Bool("empty-blocks", true, "líder propõe bloco vazio enquanto houver comando não comitado na cadeia")
	proposeTimeout := fs.Duration("propose-timeout", 10*time.Second, "timeout de /propose")
	_ = fs.Parse(args)

	logging.SetLogLevel(*logLevel)

	raw, err := os.ReadFile(filepath.Join(*dir, "cluster.json"))
	if err != nil {
		return err
	}
	var cfg clusterConfig
	if err := json.Unmarshal(raw, &cfg); err != nil {
		return err
	}

	id := hotstuff.ID(*idFlag)
	var self *replicaEntry
	infos := make([]backend.ReplicaInfo, 0, len(cfg.Replicas))
	clientNodes := make(map[string]uint32, len(cfg.Replicas))
	for i := range cfg.Replicas {
		r := &cfg.Replicas[i]
		pubPEM, err := os.ReadFile(keyPath(*dir, hotstuff.ID(r.ID), "pub"))
		if err != nil {
			return err
		}
		pub, err := keygen.ParsePublicKey(pubPEM)
		if err != nil {
			return fmt.Errorf("chave pública r%d: %w", r.ID, err)
		}
		infos = append(infos, backend.ReplicaInfo{ID: hotstuff.ID(r.ID), Address: r.ReplicaAddr, PubKey: pub})
		clientNodes[r.ClientAddr] = r.ID
		if hotstuff.ID(r.ID) == id {
			self = r
		}
	}
	if self == nil {
		return fmt.Errorf("id %d não está em cluster.json", id)
	}

	keyPEM, err := os.ReadFile(keyPath(*dir, id, "key"))
	if err != nil {
		return err
	}
	privKey, err := keygen.ParsePrivateKey(keyPEM)
	if err != nil {
		return err
	}
	cert, err := tls.LoadX509KeyPair(keyPath(*dir, id, "crt"), keyPath(*dir, id, "tlskey"))
	if err != nil {
		return err
	}
	caPEM, err := os.ReadFile(filepath.Join(*dir, "ca.crt"))
	if err != nil {
		return err
	}
	rootCAs := x509.NewCertPool()
	if !rootCAs.AppendCertsFromPEM(caPEM) {
		return errors.New("ca.crt inválido")
	}

	// Montagem de módulos espelha internal/orchestration/worker.go (createReplica).
	rules, ok := modules.GetModule[consensus.Rules](cfg.Consensus)
	if !ok {
		return fmt.Errorf("consenso desconhecido: %s", cfg.Consensus)
	}
	cryptoImpl, ok := modules.GetModule[modules.CryptoBase](cfg.Crypto)
	if !ok {
		return fmt.Errorf("crypto desconhecida: %s", cfg.Crypto)
	}
	leaderRotation, ok := modules.GetModule[modules.LeaderRotation](cfg.LeaderRotation)
	if !ok {
		return fmt.Errorf("leader rotation desconhecida: %s", cfg.LeaderRotation)
	}

	builder := modules.NewBuilder(id, privKey)
	if *emptyBlocks {
		builder.Options().SetShouldProposeEmptyBlocks()
	}
	builder.Add(
		eventloop.New(1000),
		consensus.New(rules),
		consensus.NewVotingMachine(),
		crypto.NewCache(cryptoImpl, 100),
		leaderRotation,
		synchronizer.New(synchronizer.NewViewDuration(1000, cfg.ViewTimeoutMs, 0, 1.2)),
		blockchain.New(),
		logging.New(fmt.Sprintf("hs%d", id)),
	)

	d := &daemon{
		id:             id,
		self:           *self,
		clientID:       uint32(id),
		proposeTimeout: *proposeTimeout,
		hash:           sha256.New(),
		applyCh:        make(chan execItem, 1<<16),
	}
	d.rep = replica.New(replica.Config{
		ID:             id,
		PrivateKey:     privKey,
		TLS:            true,
		Certificate:    &cert,
		RootCAs:        rootCAs,
		BatchSize:      cfg.BatchSize,
		ManagerOptions: []gorums.ManagerOption{gorums.WithDialTimeout(5 * time.Second)},
		OnExec:         d.onExec,
	}, builder)

	repLis, err := net.Listen("tcp", self.ReplicaAddr)
	if err != nil {
		return err
	}
	cliLis, err := net.Listen("tcp", self.ClientAddr)
	if err != nil {
		return err
	}
	d.rep.StartServers(repLis, cliLis)

	for _, r := range cfg.Replicas {
		for _, addr := range []string{r.ReplicaAddr, r.ClientAddr} {
			if err := waitTCP(addr, 60*time.Second); err != nil {
				return err
			}
		}
	}
	if err := d.rep.Connect(infos); err != nil {
		return err
	}
	d.rep.Start()

	mgr := clientpb.NewManager(
		gorums.WithDialTimeout(5*time.Second),
		gorums.WithGrpcDialOptions(grpc.WithTransportCredentials(credentials.NewClientTLSFromCert(rootCAs, ""))),
	)
	d.cli, err = mgr.NewConfiguration(&quorumSpec{faulty: hotstuff.NumFaulty(len(cfg.Replicas))}, gorums.WithNodeMap(clientNodes))
	if err != nil {
		return err
	}

	go d.forwardLoop()
	if *fillerInterval > 0 {
		go d.fillerLoop(*fillerInterval)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/propose", d.handlePropose)
	mux.HandleFunc("/status", d.handleStatus)
	srv := &http.Server{Addr: self.HTTPAddr, Handler: mux}
	go func() {
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatal(err)
		}
	}()
	log.Printf("cottonhs réplica %d pronta | consenso=%s crypto=%s n=%d f=%d http=%s filler=%v empty-blocks=%v",
		id, cfg.Consensus, cfg.Crypto, len(cfg.Replicas), hotstuff.NumFaulty(len(cfg.Replicas)), self.HTTPAddr, *fillerInterval, *emptyBlocks)

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	_ = srv.Close()
	d.rep.Stop()
	mgr.Close()
	return nil
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	usage := func() {
		fmt.Fprintln(os.Stderr, "uso: cottonhs keygen [flags] | cottonhs replica [flags]")
		os.Exit(2)
	}
	if len(os.Args) < 2 {
		usage()
	}
	var err error
	switch os.Args[1] {
	case "keygen":
		err = runKeygen(os.Args[2:])
	case "replica":
		err = runReplica(os.Args[2:])
	default:
		usage()
	}
	if err != nil {
		log.Fatal(err)
	}
}
