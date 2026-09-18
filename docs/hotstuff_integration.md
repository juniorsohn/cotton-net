# Integração COTTON-NET × relab/hotstuff — Análise de Viabilidade

**Objetivo:** substituir a camada de coordenação externa (hoje Raft via `raftify`, CFT) por um **BFT de complexidade linear O(n)** — HotStuff — usando a implementação acadêmica `relab/hotstuff`, mantendo o fluxo COTTON-NET (Indy + SSI) e a FSM Python intactos.

**Status deste documento:** análise para revisão **antes** de escrever código. Marca explicitamente o que está ✅ **confirmado na doc oficial** vs. 🔍 **a verificar no spike**. Para o contexto de por que HotStuff/BFT, ver `paper/revision_plan.md` §6.

**Veredito: ✅ integrável, com baixo acoplamento.** O "aplicativo" no relab/hotstuff é um par de módulos injetáveis (`Executor` + `CommandQueue`), e `Command` é bytes arbitrários — casa 1:1 com os dois pontos de costura do coordinator atual. O único código genuinamente novo é (a) um pequeno binário Go que monta a réplica e (b) a fronteira Go↔Python na execução.

---

## 1. Os dois pontos de costura

### 1.1 Nosso lado (código atual)
| Papel | Local | O que faz |
|---|---|---|
| **Entrada de ordenação** | `coordinator/main.py:450` | `await raft_node.propose(entry.encode())` — hoje empurra a intenção ao Raft |
| **Formato do payload** | `coordinator/log_entry.py` (`NymLogEntry.encode/decode`) | serializa `(entity_id, entity_type, did, verkey, role, raw_attrs)` em bytes |
| **Saída de execução** | `coordinator/fsm.py:100` `apply()` → `:121` `drain_queue` → `:131` `_submit_nym` | aplica a entrada comitada: `submit_nym`/`submit_attrib` no Indy local |
| **Retry idempotente** | `coordinator/pending.py` | fila de reenvio com backoff quando o Indy local falha |

Ponto-chave (já registrado em `revision_plan.md`): a FSM é **agnóstica ao motor de ordenação**. O determinismo vem do *log ordenado*; o write no Indy é efeito colateral idempotente. Trocar o motor não toca `_submit_nym`.

### 1.2 Lado relab/hotstuff (assinaturas confirmadas na doc oficial)
✅ Confirmado em [pkg.go.dev/.../modules](https://pkg.go.dev/github.com/relab/hotstuff/modules):

```go
// SAÍDA — chamado quando um comando é comitado (nosso hook de execução):
type Executor interface {
    Exec(cmd hotstuff.Command)
}
type ExecutorExt interface {          // variante em nível de bloco
    Exec(block *hotstuff.Block)
}

// ENTRADA — fonte dos comandos a propor:
type CommandQueue interface {
    Get(ctx context.Context) (cmd hotstuff.Command, ok bool)
}

// VALIDADE/DEDUP — onde vai a verificação do quorum-cert do super-nó (§4.2):
type Acceptor interface {
    Accept(hotstuff.Command) bool
    Proposed(hotstuff.Command)
}
```

✅ `type Command string` — "can hold arbitrary bytes of any length" → o `NymLogEntry.encode()` entra direto, sem novo formato.
✅ Injeção via `modules.Builder`: `NewBuilder(id, pk)` → `builder.Add(customExecutor, ...)` → `Build()`; réplica montada com `replica.New(conf Config, builder modules.Builder)`.
✅ Crypto `crypto/bls12` = **threshold signatures BLS12-381 agregadas** → o QC linear que dá O(n) *e* serve de base para o binding de super-nó.
✅ Consenso: `chainedhotstuff` (pipeline de 3 fases do paper), `fasthotstuff`, `simplehotstuff`.
✅ Ciclo de vida da réplica: `New` → `StartServers(replicaListen, clientListen)` → `Connect(replicas)` → `Run(ctx)` (bloqueante) / `Start()` (goroutine) → `Stop`/`Close`.

---

## 2. Arquitetura de integração (por máquina-coordenador)

```
 workload client ──HTTP──▶ [Python coordinator /register]         (mantido: FastAPI + métricas)
                                    │ NymLogEntry.encode() → bytes
                                    ▼ submit command
                           [Go: réplica relab/hotstuff]  ⇄─ BFT ordering (QC BLS, O(n)) ─⇄  réplicas dos outros Sₙ coordenadores
                                    │ Executor.Exec(cmd)   (mesma ordem em TODAS as réplicas)
                                    ▼ IPC local (gRPC/HTTP loopback)
                           [Python applier: _submit_nym → super-nó Indy local]  + pending retry + Prometheus
```

- **Ordenação** migra do `raftify` para a réplica Go (BFT).
- **Execução** (`_submit_nym`, aries-askar/Indy) permanece Python, chamada pelo `Executor` via IPC local.
- `raftify` **fica lado a lado como baseline CFT** — o paper quer a comparação Raft×BFT (revision_plan §6.4c). Selecionável por env var (mesmo padrão do `WORKLOAD_PARITY`).

---

## 3. Caminho de menor esforço vs. completo

**MVP (spike + primeira campanha):**
- Usar o **client server embutido** do relab (`clientsrv`) + **CommandQueue padrão**; só implementar **`Executor` custom** que chama o applier Python. Menor cola possível.
- Crypto = `bls12`; consenso = `chainedhotstuff`; membership = os Sₙ coordenadores.

**Completo (blindagem de segurança, §4.2):**
- Implementar **`Acceptor.Accept(cmd)`** para verificar o quorum-cert do super-nó de origem antes de aceitar a intenção.
- Eventual **`CommandQueue` custom** se quisermos controlar batching/prioridade.

---

## 4. Onde cada peça de segurança encaixa

### 4.1 Ordenação bizantina entre coordenadores — ✅ resolvido pelo próprio HotStuff
`f ≤ ⌊(Sₙ−1)/3⌋` coordenadores bizantinos toleráveis. Conserta equivocação/supressão *entre* coordenadores.

### 4.2 Fidelidade coordenador↔super-nó (a armadilha crítica — revision_plan §6.3-2)
O BFT externo **não** impede um coordenador bizantino de propor uma intenção que seu super-nó nunca aprovou. Fecho: cada intenção carrega o **quorum-cert do RBFT interno do super-nó de origem**; a interface **`Acceptor.Accept()` é o lugar natural** para rejeitar intenções sem cert válido — reutilizando a mesma máquina `bls12`. **Algoritmo BFT + cert de super-nó são inseparáveis.**

### 4.3 Experimento adversarial — quase de graça
✅ O relab traz o pacote `consensus/byzantine` (comportamentos bizantinos por wrapping das interfaces) + estratégia **Twins**. Isso entrega o experimento de "coordenador bizantino" (revision_plan C1'/§6d) sem instrumentação nova.

---

## 5. Riscos e questões a resolver no spike (honestidade)

| # | Risco / incógnita | Mitigação |
|---|---|---|
| R1 | 🔍 API exata de submissão de comando pelo cliente (`clientsrv`) vs. `CommandQueue` custom | primeira coisa a validar no spike |
| R2 | 🔍 Rede **Gorums** (portas/TLS) coexistindo com pools Indy + overlay Swarm — atenção ao esgotamento de IPAM já visto (memória `feedback_swarm_ipam_exhaustion`) | mapear portas/serviços por host antes de escalar Sₙ |
| R3 | 🔍 Overhead do IPC Go→Python na execução | medir (loopback gRPC ~sub-ms); comparar aos 7–12 ms de overhead de coordenador atuais (Tab. III do paper) |
| R4 | 🔍 Setup/distribuição de chaves BLS entre coordenadores; binding do cert de super-nó é trabalho cripto adicional | relab faz keygen das réplicas; o cert de super-nó (§4.2) é fase 2 |
| R5 | 🔍 API research-grade (v0.5.0), doc fina | o spike É a prova; fixar versão/commit |

---

## 6. Plano do spike (~1 semana) — critérios de aceite

1. ✅ 4 réplicas `relab/hotstuff` (`bls12` + `chainedhotstuff`) alcançam consenso localmente.
2. ✅ `Executor` custom recebe os comandos comitados **na mesma ordem** nas 4 réplicas.
3. ✅ Comando carregando um payload `NymLogEntry` faz round-trip: submit → commit → `Exec()` chama um applier-stub externo (loopback).
4. ✅ Matar 1 de 4 (f=1) → liveness se mantém (prova o BFT).

Passando 1–4: ligar o applier Python real (`_submit_nym`) → depois §4.2 (Acceptor + cert). Só então mexer no coordinator de produção.

---

## 7. Fontes (confiáveis, revisáveis)

**Implementação (API autoritativa):**
- Repositório: https://github.com/relab/hotstuff
- Módulos/interfaces (assinaturas citadas): https://pkg.go.dev/github.com/relab/hotstuff/modules
- Construção da réplica: https://pkg.go.dev/github.com/relab/hotstuff/replica
- Crypto BLS12-381 (threshold sigs): https://pkg.go.dev/github.com/relab/hotstuff/crypto/bls12
- Consenso (variantes): https://pkg.go.dev/github.com/relab/hotstuff/consensus
- Networking Gorums: https://github.com/relab/gorums

**Protocolo (revisado por pares):**
- Yin, Malkhi, Reiter, Gueta, Abraham. *HotStuff: BFT Consensus with Linearity and Responsiveness.* PODC 2019. https://dl.acm.org/doi/10.1145/3293611.3331591 · preprint https://arxiv.org/abs/1803.05069

**Nosso código (âncoras de costura):**
- `coordinator/main.py:450` (propose) · `coordinator/fsm.py:100,121,131` (apply/drain/submit) · `coordinator/log_entry.py` (encode) · `coordinator/pending.py` (retry)

> ⚠️ Assinaturas e capacidades marcadas ✅ vêm da doc oficial do relab/hotstuff consultada em 11/set/2026 (módulo v0.5.0). Itens 🔍 dependem de verificação hands-on no spike — não tomar como fato até validados.
