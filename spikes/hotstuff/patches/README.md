# Patch no relab/hotstuff v0.5.0

O `relab/` é um clone do upstream e não é versionado aqui. O `setup.sh` o
reconstrói de forma determinística: devolve ao estado do upstream (`git checkout
-- .`) e aplica `0001-cottonnet-relab.patch`. **Editar `relab/` direto não
sobrevive a um setup** — para mudar o relab: edite, regenere o patch com
`git -C relab diff > patches/0001-cottonnet-relab.patch`, e só então rode o setup.

São três mudanças, todas marcadas com `(COTTON-NET)` no código.

## 1. Gancho de execução — `replica/{replica,clientsrv}.go`

O plano original era plugar nosso executor pela API pública, e **não dá**: o
`replica.New` registra o servidor de cliente por último e o `Build()` inverte a
ordem, então um `Executor` adicionado via `builder.Add` nunca é chamado. O patch
adiciona um callback opcional `OnExec` em `replica.Config`, chamado para cada
comando comitado, em ordem de execução. É por onde a NYM sai do Go para o
coordinator Python.

## 2. Blocos vazios — `modules/options.go`, `replica/cmdcache.go`, `consensus/consensus.go`

Conserta os dois defeitos que faziam uma NYM isolada nunca comitar:

- **off-by-one no `cmdCache`**: o produtor sinaliza em `Len() >= batchSize` mas o
  consumidor esperava `Len() > batchSize`, então com lote 1 a NYM sozinha nunca
  saía da fila. Corrigido para `< batchSize`; o `Get` também passou a liberar
  **lote parcial** quando a view expira (batch timeout), em vez de não propor nada;
- **3-cadeia sem sucessores**: opção `ShouldProposeEmptyBlocks` (desligada por
  padrão, para não alterar os benchmarks do relab). Ligada, se houver bloco COM
  comandos entre o último commit e o topo da cadeia, o líder propõe na hora —
  bloco vazio se a fila estiver vazia. A varredura da cadeia é o freio: quando o
  último bloco com comandos comita, ela devolve false e a cadeia para de crescer.

Medido com 4 réplicas locais: NYM isolada passou de **nunca comitar** para ~20 ms;
lote de 20, mediana 75 → 37 ms.

## 3. Nome TLS fixo — `replica/replica.go`

O gorums resolve o endereço para IP antes de discar (`NewRawNodeWithID` guarda
`tcpAddr.String()`), e o `tls.Config` do relab não define `ServerName` — então o
Go verifica o certificado contra o **IP**. Em container isso é insolúvel: o IP é
atribuído no deploy e nenhum certificado gerado antes pode carregá-lo. O erro
concreto era `x509: certificate is valid for 127.0.0.1, not 172.18.0.2`.

O patch adiciona `TLSServerName` a `replica.Config`. O `cottonhs keygen -hosts`
põe um nome comum (`cottonhs`) no SAN de todos os certificados e o grava no
`cluster.json`; a réplica o usa na verificação.

**Consequência que vale declarar no paper:** o TLS passa a autenticar "membro da
nossa CA", não "esta réplica específica". A identidade de réplica não depende
disso — cada mensagem do consenso é assinada e verificada contra a chave pública
da réplica, que viaja no `cluster.json`. O TLS aqui é confidencialidade e
integridade de transporte.
