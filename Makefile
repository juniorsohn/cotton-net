# COTTONTRUST / COTTON-NET — Makefile
SHELL := /bin/bash
#
# ── Workflow COTTON-NET (RAFT + supernodos) ───────────────────────────────────
#   1. make swarm-init            (uma vez só)
#   2. make von-start NODES=32    (varia entre experimentos)
#   3. make deploy                (sobe infraestrutura — coordinators, monitoring)
#   4. make client-start          (inicia o experimento quando tudo estiver pronto)
#   5. make logs-client           (acompanha a execução)
#   6. make client-stop           (encerra o client manualmente, se necessário)
#   7. make teardown && make von-stop
#   8. Repete a partir do passo 2 com NODES diferente
#
# ── Workflow COTTONTRUST Distribuído (Indy puro, multi-máquina) ───────────────
#   1. make swarm-init            (uma vez só, compartilhado com COTTON-NET)
#   2. make ct-config NODES=16    (gera stack YAML + docker config no Swarm)
#   3. make ct-deploy             (sobe nós Indy + webserver distribuído)
#   4. make ct-status             (aguarda todos os nós ficarem Running)
#   5. make ct-client-start       (inicia o experimento)
#   6. make ct-logs-client        (acompanha a execução)
#   7. make ct-stop               (encerra stack e remove config)
#   8. Repete a partir do passo 2 com NODES diferente

NODES      ?= 32
SUPERNODOS ?= 4
STACK      ?= cottontrust
CT_STACK   ?= ct
CN_STACK   ?= cn
SSH_USER   ?= g11718038933
VON_DIR    ?= /mnt/prj/g11718038933/cotton-net_2026/von-network
# Comando SSH usado pelo ct-stop. Default 'ssh' (senha interativa). O loop
# ct-client-10runs-fresh sobrescreve com 'sshpass -e ssh' (senha via env SSHPASS,
# pedida uma vez) para rodar as remoções nas baias sem prompt a cada run.
SSH        ?= ssh

export DOCKER_API_VERSION ?= 1.41

# ── Máquinas do cluster ───────────────────────────────────────────────────────
# IPs das baias (10.10.20.15x)
BAIA1_IP   := 10.10.20.151
BAIA2_IP   := 10.10.20.152
BAIA3_IP   := 10.10.20.153
BAIA4_IP   := 10.10.20.154
BAIA5_IP   := 10.10.20.155

# Hostnames reais (o que aparece em `docker node ls` e nos constraints do Swarm)
BAIA1_HOST := flores
BAIA2_HOST := corisco
BAIA3_HOST := baiacu
BAIA4_HOST := pernambuco
BAIA5_HOST := cacao

# Registry em baia1
REGISTRY   ?= localhost:5000

# Listas exportadas para os scripts shell
BAIA_IPS   := $(BAIA1_IP) $(BAIA2_IP) $(BAIA3_IP) $(BAIA4_IP) $(BAIA5_IP)
BAIA_NAMES := $(BAIA1_HOST) $(BAIA2_HOST) $(BAIA3_HOST) $(BAIA4_HOST) $(BAIA5_HOST)

export REGISTRY SSH_USER VON_DIR BAIA_IPS BAIA_NAMES

.DEFAULT_GOAL := help

help:
	@echo ""
	@echo "COTTONTRUST / COTTON-NET"
	@echo "════════════════════════════════════════"
	@echo "  swarm-init              Inicializa Docker Swarm"
	@echo "  registry-start          Sobe registry em $(BAIA1_IP):5000"
	@echo "  von-config  NODES=N     Gera start_nodes.sh no NFS (roda uma vez)"
	@echo "  von-patch               Patcha von-network-base: limite 100 → 10000 nós"
	@echo "  von-patch-scale         Patch p/ pools grandes: cap réplicas + VC timeout"
	@echo "  von-local-build         Build + patch da imagem (sem iniciar rede)"
	@echo "  von-local-start         Rebuild + patch + start na baia atual"
	@echo "  von-local-stop          Para o supernodo local"
	@echo "  von-start   NODES=N     von-config + instrução para cada baia"
	@echo "  von-stop                Para todos os VON Networks via SSH"
	@echo "  von-status              Verifica genesis endpoints"
	@echo "  build                   Constrói imagens Docker"
	@echo "  push                    Envia imagens para $(REGISTRY)"
	@echo "  deploy                  Deploy do stack COTTON-NET no Swarm"
	@echo "  teardown                Remove o stack COTTON-NET"
	@echo "  logs-client             Logs do cottonclient (COTTON-NET)"
	@echo "  logs-coord NODE=N       Logs do coordinator-N"
	@echo "  status                  Status do stack COTTON-NET"
	@echo "  client-start            Inicia cottonclient COTTON-NET (0 → 1)"
	@echo "  client-stop             Para cottonclient COTTON-NET  (1 → 0)"
	@echo "  client-10runs RUNS=N    N runs seq. (CSV runN + analyze_metrics report)"
	@echo "  experiment NODES=N      von-start + deploy de uma vez"
	@echo ""
	@echo "  ── COTTONTRUST Distribuído (Indy puro, multi-máquina) ──"
	@echo "  ct-config   NODES=N     Gera stack YAML + docker config no Swarm"
	@echo "  ct-deploy               Deploy do stack distribuído"
	@echo "  ct-stop                 Remove o stack + docker config"
	@echo "  ct-status               Status do stack distribuído"
	@echo "  ct-genesis              Verifica genesis no webserver (cacao:9000)"
	@echo "  ct-client-start         Inicia cottonclient distribuído (0 → 1)"
	@echo "  ct-client-stop          Para cottonclient distribuído  (1 → 0)"
	@echo "  ct-client-10runs RUNS=N N runs seq. (mesmo ledger — só p/ debug)"
	@echo "  ct-client-10runs-fresh  N runs com ledger FRESCO/run (RUNS NODES SETTLE)"
	@echo "  ct-logs-client          Logs do cottonclient"
	@echo "  ct-logs-node NODE=N     Logs do nó Indy N (stack CT)"
	@echo "  ct-logs-web             Logs do webserver"
	@echo ""
	@echo "  ── COTTON-NET Distribuído (Indy fragmentado, RAFT entre super-nós) ──"
	@echo "  cn-config   NODES=N SUPERNODOS=S  Gera stack YAML + docker configs"
	@echo "  cn-deploy               Deploy do stack (todos os SN simultâneos)"
	@echo "  cn-deploy-seq           Deploy sequencial: um SN por vez (recomendado)"
	@echo "  cn-stop                 Remove stack + configs + volumes"
	@echo "  cn-status               Status do stack COTTON-NET distribuído"
	@echo "  cn-genesis              Verifica genesis de cada baia (S_n×:9000)"
	@echo "  cn-client-start         Inicia cottonclient COTTON-NET (0 → 1)"
	@echo "  cn-client-stop          Para cottonclient COTTON-NET  (1 → 0)"
	@echo "  cn-client-10runs RUNS=N N runs seq. (CSV runN + analyze_metrics report)"
	@echo "  cn-client-10runs-fresh  N runs com ledgers FRESCOS/run (RUNS NODES SUPERNODOS SETTLE)"
	@echo "  cn-logs-client          Logs do cottonclient"
	@echo "  cn-logs-coord NODE=N    Logs do coordinator-N"
	@echo ""

swarm-init:
	@chmod +x scripts/swarm_init.sh && ./scripts/swarm_init.sh

registry-start:
	@ssh $(SSH_USER)@$(BAIA1_IP) "docker run -d -p 5000:5000 --restart always \
		--name registry registry:2 2>/dev/null || echo '(já rodando)'"

von-config:
	@# Gera start_nodes.sh no von-network compartilhado (NFS) — roda uma vez
	@chmod +x scripts/start_von.sh
	@./scripts/start_von.sh $(NODES) $(SUPERNODOS)

von-patch:
	@# Aplica patch no limite de nós do indy-plenum (100 → 10000) na imagem local.
	@# Requer que von-network-base já exista (make von-local-build ou ./manage build).
	@chmod +x scripts/patch_von_image.sh && ./scripts/patch_von_image.sh

von-patch-scale:
	@# Patch de ESCALA p/ pools grandes (192/256+): cap de réplicas (min(f+1,K))
	@# + view-change timeout maior. Rodar em CADA baia que roda nós, após o
	@# von-local-build. ⚠️ Muda o consenso de TODOS os tamanhos — re-colete os
	@# cenários com a mesma imagem (declarar o cap no paper).
	@# Uso: make von-patch-scale [REPLICA_CAP=4] [VC_TIMEOUT=600]
	@chmod +x scripts/patch_von_scale.sh
	@REPLICA_CAP=$(or $(REPLICA_CAP),4) VC_TIMEOUT=$(or $(VC_TIMEOUT),600) ./scripts/patch_von_scale.sh

von-local-build:
	@# Reconstrói von-network-base na baia atual e aplica o patch indy-plenum.
	@# Para o fluxo CN distribuído: rodar em cada baia antes de make cn-deploy.
	@echo "🔧 Build von-network-base..."
	@cd $(VON_DIR) && DOCKER_API_VERSION=1.41 ./manage build
	@$(MAKE) von-patch

von-local-start:
	@# Roda na baia atual: rebuild + patch + ./manage start <IP local>
	@$(VON_DIR)/von_local_start.sh

von-local-stop:
	@# Para o supernodo local (mantém volumes)
	@cd $(VON_DIR) && DOCKER_API_VERSION=1.41 ./manage stop 2>/dev/null || true

von-start: von-config
	@echo "→ Agora faça SSH em cada baia e execute: make von-local-start"

von-stop:
	@chmod +x scripts/stop_von.sh && ./scripts/stop_von.sh

von-status:
	@for ip in $(BAIA1_IP) $(BAIA2_IP) $(BAIA3_IP) $(BAIA4_IP); do \
		curl -sf http://$$ip:9000/genesis > /dev/null \
			&& echo "  ✅ http://$$ip:9000/genesis" \
			|| echo "  ❌ http://$$ip:9000/genesis"; \
	done

build:
	docker build -t $(REGISTRY)/cottontrust-client:latest      -f client/dockerfile .
	docker build -t $(REGISTRY)/cottontrust-coordinator:latest  -f coordinator/dockerfile .
	docker build -t $(REGISTRY)/indy-exporter:latest           monitoring/indy-exporter/

push: build
	docker push $(REGISTRY)/cottontrust-client:latest
	docker push $(REGISTRY)/cottontrust-coordinator:latest
	docker push $(REGISTRY)/indy-exporter:latest

# Rebuild + push só da imagem do client (CT não usa o coordinator).
# Útil para iterar no client sem recompilar o raftify do coordinator.
client-push:
	docker build -t $(REGISTRY)/cottontrust-client:latest -f client/dockerfile .
	docker push  $(REGISTRY)/cottontrust-client:latest

deploy:
	docker stack deploy --resolve-image=never -c docker-compose.yml $(STACK)

teardown:
	docker stack rm $(STACK)

client-start:
	docker service scale $(STACK)_cottonclient=1

client-stop:
	docker service scale $(STACK)_cottonclient=0

# ── Driver de N runs sequenciais do cottonclient ──────────────────────────────
# Escala 0→1, espera a task COMPLETAR (exit 0), escala 1→0 e repete RUNS vezes.
# NÃO limpa volumes: o collector usa next_run_path(), então cada execução grava
# um CSV novo (..._run1.csv, ..._run2.csv, ...) no volume *_client-output.
# Uso: make ct-client-10runs            (10 por padrão)
#      make cn-client-10runs RUNS=5     (override do nº de runs)
# Ctrl-C interrompe; a task em curso é encerrada no próximo scale=0.
RUNS ?= 10
POLL ?= 5
# RESULTS_DIR: mesmo host-dir que os stacks CT/CN montam em /app/output (bind).
# Após cada run, roda analyze_metrics.py no CSV recém-gerado → grava .report.md.
RESULTS_DIR ?= /mnt/prj/g11718038933/cotton-net_2026/results
define run_client_n
	@set -e; svc=$(1)_cottonclient; \
	echo "══ $$svc — $(RUNS) run(s) (volumes preservados; CSV runN automático) ══"; \
	for i in $$(seq 1 $(RUNS)); do \
	  echo "── run $$i/$(RUNS) ──"; \
	  docker service scale --detach $$svc=0 >/dev/null 2>&1 || true; \
	  prev=$$(docker service ps $$svc -q --no-trunc 2>/dev/null | head -1); \
	  docker service scale --detach $$svc=1 >/dev/null; \
	  echo "   aguardando nova task iniciar..."; \
	  until cur=$$(docker service ps $$svc -q --no-trunc 2>/dev/null | head -1); \
	        [ -n "$$cur" ] && [ "$$cur" != "$$prev" ]; do sleep 2; done; \
	  echo "   task $${cur:0:12} rodando; aguardando concluir..."; \
	  while :; do \
	    st=$$(docker service ps $$svc --no-trunc --format '{{.CurrentState}}' 2>/dev/null | head -1); \
	    case "$$st" in \
	      Complete*) echo "   run $$i OK ($$st)"; break ;; \
	      Failed*|Rejected*) echo "   run $$i FALHOU: $$st"; docker service scale --detach $$svc=0 >/dev/null 2>&1 || true; exit 1 ;; \
	      *) sleep $(POLL) ;; \
	    esac; \
	  done; \
	  docker service scale --detach $$svc=0 >/dev/null; sleep 2; \
	  csv=$$(ls -t $(RESULTS_DIR)/*.csv 2>/dev/null | head -1); \
	  if [ -n "$$csv" ]; then \
	    echo "   analisando $$csv"; \
	    python3 scripts/analyze_metrics.py "$$csv" --md "$${csv%.csv}.report.md" \
	      || echo "   [aviso] analyze_metrics.py falhou em $$csv"; \
	  else \
	    echo "   [aviso] nenhum CSV em $(RESULTS_DIR) (stack base usa volume nomeado — ajuste RESULTS_DIR)"; \
	  fi; \
	done; \
	echo "══ concluído: $(RUNS) run(s). CSVs+reports em $(RESULTS_DIR) ══"
endef

client-10runs:
	$(call run_client_n,$(STACK))

NODE ?= 1
logs-client:
	docker service logs -f $(STACK)_cottonclient

logs-coord:
	docker service logs -f $(STACK)_coordinator-$(NODE)

status:
	docker stack ps $(STACK) --no-trunc
	@echo ""
	docker stack services $(STACK)

experiment: von-start deploy
	@echo ""
	@echo "Experimento iniciado | NODES=$(NODES) SUPERNODOS=$(SUPERNODOS)"
	@echo "Monitoramento: http://$(BAIA5_IP):3002"
	@echo "Prometheus:    http://$(BAIA5_IP):9091"


# ── COTTONTRUST Distribuído ───────────────────────────────────────────────────
# Stack independente do COTTON-NET: nós Indy RBFT distribuídos em 4 máquinas.
# A imagem von-network-base deve estar disponível em todas as baias (docker pull
# ou build local antes do deploy).

ct-config:
	@chmod +x scripts/gen_cottontrust_stack.sh
	@./scripts/gen_cottontrust_stack.sh $(NODES)

ct-deploy:
	docker stack deploy -c docker-stack-cottontrust.yml $(CT_STACK)

ct-stop:
	@echo "Removendo stack $(CT_STACK)..."
	-docker stack rm $(CT_STACK)
	@echo "Removendo docker configs von-gen-tx-* (independente de NODES)..."
	-docker config ls -q --filter name=von-gen-tx-n 2>/dev/null | xargs -r docker config rm 2>/dev/null || true
	@echo "Aguardando o stack encerrar completamente (poll local, sem SSH)..."
	@for i in $$(seq 1 60); do \
		n=$$(docker stack ps $(CT_STACK) -q 2>/dev/null | wc -l); \
		[ "$$n" -eq 0 ] && break; \
		sleep 2; \
	done
	@sleep 5
	@echo "Removendo volumes de ledger (cacao)..."
	-$(SSH) $(SSH_USER)@$(BAIA5_IP) \
		"docker volume rm $(CT_STACK)_webserver-ledger $(CT_STACK)_webserver-cli \
		$(CT_STACK)_client-output $(CT_STACK)_client-wallets 2>/dev/null || true"
	@echo "Removendo volumes de nós (flores/corisco/baiacu/pernambuco)..."
	@for ip in $(BAIA1_IP) $(BAIA2_IP) $(BAIA3_IP) $(BAIA4_IP); do \
		$(SSH) $(SSH_USER)@$$ip \
			"docker volume ls -q | grep '^$(CT_STACK)_node' | xargs -r docker volume rm 2>/dev/null || true"; \
	done
	@echo "✅ Stack, config e volumes removidos."

ct-status:
	docker stack ps $(CT_STACK) --no-trunc

ct-genesis:
	@curl -sf http://$(BAIA5_IP):9000/genesis > /dev/null \
		&& echo "✅ Genesis disponível: http://$(BAIA5_IP):9000/genesis" \
		|| echo "❌ Genesis indisponível em $(BAIA5_IP):9000"

ct-client-start:
	docker service scale $(CT_STACK)_cottonclient=1

ct-client-stop:
	docker service scale $(CT_STACK)_cottonclient=0

ct-client-10runs:
	$(call run_client_n,$(CT_STACK))

# ── CT: N runs com LEDGER FRESCO por run (reset + redeploy a cada run) ─────────
# Necessário no CT: DIDs são determinísticos e o ledger Indy é append-only, então
# re-registrar entidades com role no mesmo ledger é rejeitado ("TRUSTEE can not
# touch role field"). Por isso cada run recria a rede do zero.
# ct-stop entra via SSH nas baias p/ apagar volumes → a senha é pedida UMA vez
# (read -s → env SSHPASS → sshpass; não aparece no ps/argv) e reusada nas N runs.
# Requer 'sshpass'. Params: RUNS, NODES, SETTLE (espera pós-genesis), READY_TIMEOUT.
# Uso: make ct-client-10runs-fresh RUNS=10 NODES=64 [SETTLE=90]
SETTLE        ?= 60
READY_TIMEOUT ?= 600
ct-client-10runs-fresh:
	@command -v sshpass >/dev/null 2>&1 || { echo "ERRO: 'sshpass' não instalado (ct-stop apaga volumes via SSH com senha). Instale: sudo apt-get install -y sshpass"; exit 1; }
	@read -rs -p "Senha SSH ($(SSH_USER)@baias): " SSHPASS; echo; export SSHPASS; \
	svc=$(CT_STACK)_cottonclient; \
	echo "══ CT fresh-ledger — $(RUNS) run(s), NODES=$(NODES) (rede recriada por run) ══"; \
	for i in $$(seq 1 $(RUNS)); do \
	  echo "──────── run $$i/$(RUNS) ────────"; \
	  echo "   [1/4] ct-stop (remove stack + volumes via SSH)"; \
	  $(MAKE) --no-print-directory ct-stop SSH='sshpass -e ssh -o StrictHostKeyChecking=accept-new' NODES=$(NODES) || { echo "   ct-stop falhou (senha?)"; exit 1; }; \
	  echo "   [2/4] ct-config + ct-deploy (NODES=$(NODES))"; \
	  $(MAKE) --no-print-directory ct-config NODES=$(NODES) >/dev/null || { echo "   ct-config falhou"; exit 1; }; \
	  $(MAKE) --no-print-directory ct-deploy || { echo "   ct-deploy falhou"; exit 1; }; \
	  docker service update --restart-condition none --detach $$svc >/dev/null 2>&1 || true; \
	  echo "   [3/4] aguardando genesis em http://$(BAIA5_IP):9000 (até $(READY_TIMEOUT)s)"; \
	  t=0; until curl -sf http://$(BAIA5_IP):9000/genesis >/dev/null 2>&1; do \
	    sleep 5; t=$$((t+5)); [ $$t -ge $(READY_TIMEOUT) ] && { echo "   timeout esperando genesis"; exit 1; }; \
	  done; \
	  echo "   genesis ok; estabilizando $(SETTLE)s..."; sleep $(SETTLE); \
	  echo "   [4/4] client run $$i"; \
	  prev=$$(docker service ps $$svc -q --no-trunc 2>/dev/null | head -1); \
	  docker service scale --detach $$svc=1 >/dev/null; \
	  until cur=$$(docker service ps $$svc -q --no-trunc 2>/dev/null | head -1); \
	        [ -n "$$cur" ] && [ "$$cur" != "$$prev" ]; do sleep 2; done; \
	  echo "      task $${cur:0:12} rodando; aguardando concluir..."; \
	  while :; do \
	    st=$$(docker service ps $$svc --no-trunc --format '{{.CurrentState}}' 2>/dev/null | head -1); \
	    case "$$st" in \
	      Complete*) echo "      run $$i OK ($$st)"; break ;; \
	      Failed*|Rejected*) echo "      run $$i FALHOU: $$st"; docker service scale --detach $$svc=0 >/dev/null 2>&1 || true; exit 1 ;; \
	      *) sleep $(POLL) ;; \
	    esac; \
	  done; \
	  docker service scale --detach $$svc=0 >/dev/null 2>&1 || true; \
	  csv=$$(ls -t $(RESULTS_DIR)/*.csv 2>/dev/null | head -1); \
	  if [ -n "$$csv" ]; then python3 scripts/analyze_metrics.py "$$csv" --md "$${csv%.csv}.report.md" >/dev/null 2>&1 || echo "      [aviso] analyze_metrics falhou"; fi; \
	done; \
	echo "══ concluído: $(RUNS) run(s) fresh-ledger. CSVs+reports em $(RESULTS_DIR) ══"

ct-logs-client:
	docker service logs -f $(CT_STACK)_cottonclient

# Logs de um nó Indy do stack CT (equivalente ao './manage logs' do fluxo CN,
# que não enxerga estes containers — no CT os nós sobem via Swarm, não compose).
# Uso: make ct-logs-node NODE=42
ct-logs-node:
	docker service logs -f $(CT_STACK)_node$(NODE)

ct-logs-web:
	docker service logs -f $(CT_STACK)_webserver


# ── COTTON-NET Distribuído ────────────────────────────────────────────────────
# K_n nós de cada super-nó distribuídos pelas 4 baias — mesma régua do CT.
# Garante que a comunicação Indy interna percorre a rede física, não localhost.

cn-config:
	@chmod +x scripts/gen_cottonnet_stack.sh
	@./scripts/gen_cottonnet_stack.sh $(NODES) $(SUPERNODOS)

cn-deploy:
	docker stack deploy --resolve-image=never -c docker-stack-cottonnet.yml $(CN_STACK)

# Deploy sequencial: sobe um SN por vez, aguardando genesis antes de avançar.
# Evita race condition de agendamento e contenda NFS quando todos os 128 nós
# tentam iniciar ao mesmo tempo.
cn-deploy-seq:
	@KN=$$(( $(NODES) / $(SUPERNODOS) )); \
	BAIA_IPS_ARR=($(BAIA1_IP) $(BAIA2_IP) $(BAIA3_IP) $(BAIA4_IP)); \
	echo "=== Deploy sequencial COTTON-NET: $(SUPERNODOS) SN × $$KN nós ==="; \
	docker stack deploy --resolve-image=never -c docker-stack-cottonnet.yml $(CN_STACK); \
	echo "Pausando nós SN2..SN$(SUPERNODOS) (aguardando vez de cada SN)..."; \
	for s in $$(seq 2 $(SUPERNODOS)); do \
		( for n in $$(seq 1 $$KN); do \
			docker service update --replicas=0 --detach \
				$(CN_STACK)_cn-sn$${s}-node$${n} >/dev/null 2>&1; \
		done; \
		docker service update --replicas=0 --detach \
			$(CN_STACK)_webserver-sn$${s} >/dev/null 2>&1; \
		) & \
	done; \
	wait; \
	echo "SN2-SN$(SUPERNODOS) pausados. Iniciando sequência..."; \
	for s in $$(seq 1 $(SUPERNODOS)); do \
		echo ""; \
		echo "--- SN$$s: escalando $$KN nós Indy + webserver ---"; \
		for n in $$(seq 1 $$KN); do \
			docker service update --replicas=1 --detach \
				$(CN_STACK)_cn-sn$${s}-node$${n} >/dev/null 2>&1; \
		done; \
		docker service update --replicas=1 --detach \
			$(CN_STACK)_webserver-sn$${s} >/dev/null 2>&1; \
		WEBIP=$${BAIA_IPS_ARR[$$((s-1))]}; \
		echo "Aguardando genesis SN$$s em http://$$WEBIP:9000 ..."; \
		until curl -sf "http://$$WEBIP:9000/genesis" >/dev/null 2>&1; do \
			printf '.'; sleep 15; \
		done; \
		echo " ✅ SN$$s OK"; \
	done; \
	echo ""; \
	echo "✅ Todos os $(SUPERNODOS) supernodos com genesis OK"

cn-stop:
	@echo "Removendo stack $(CN_STACK)..."
	-docker stack rm $(CN_STACK)
	@echo "Aguardando tasks encerrarem (poll com timeout)..."
	@for i in $$(seq 1 60); do \
		n=$$(docker stack ps $(CN_STACK) -q 2>/dev/null | wc -l); \
		[ "$$n" -eq 0 ] && break; \
		printf '.'; sleep 3; \
	done; echo
	@echo "Varrendo containers cn_ órfãos em cada baia (libera portas host, ex.: 9000)..."
	@for ip in $(BAIA1_IP) $(BAIA2_IP) $(BAIA3_IP) $(BAIA4_IP) $(BAIA5_IP); do \
		$(SSH) $(SSH_USER)@$$ip \
			"docker ps -aq --filter name=$(CN_STACK)_ | xargs -r docker rm -f 2>/dev/null || true"; \
	done
	@echo "Removendo configs (por filtro de nome, independente de NODES)..."
	-docker config ls -q --filter name=cn-gen-tx-sn    2>/dev/null | xargs -r docker config rm 2>/dev/null || true
	-docker config ls -q --filter name=cn-start-node-sn 2>/dev/null | xargs -r docker config rm 2>/dev/null || true
	@echo "Removendo volumes das baias..."
	@for ip in $(BAIA1_IP) $(BAIA2_IP) $(BAIA3_IP) $(BAIA4_IP) $(BAIA5_IP); do \
		$(SSH) $(SSH_USER)@$$ip \
			"docker volume ls -q | grep '^$(CN_STACK)_' | xargs -r docker volume rm 2>/dev/null || true"; \
	done
	@echo "✅ Stack, configs e volumes removidos."

cn-status:
	docker stack ps $(CN_STACK) --no-trunc
	@echo ""
	docker stack services $(CN_STACK)

cn-genesis:
	@echo "Verificando genesis dos super-nós (cada baia:9000)..."
	@for ip in $(BAIA1_IP) $(BAIA2_IP) $(BAIA3_IP) $(BAIA4_IP); do \
		curl -sf http://$$ip:9000/genesis > /dev/null \
			&& echo "  ✅ http://$$ip:9000/genesis" \
			|| echo "  ❌ http://$$ip:9000/genesis"; \
	done

cn-client-start:
	docker service scale $(CN_STACK)_cottonclient=1

cn-client-stop:
	docker service scale $(CN_STACK)_cottonclient=0

cn-client-10runs:
	$(call run_client_n,$(CN_STACK))

# ── CN: N runs com LEDGERS FRESCOS por run (reset + redeploy a cada run) ───────
# Mesma motivação do ct-client-10runs-fresh (DIDs determinísticos + ledger
# append-only), mas com as diferenças do CN:
#   - cn-stop também varre containers órfãos via SSH (senha pedida UMA vez);
#   - o deploy é o cn-deploy-seq, que já aguarda o genesis de CADA super-nó;
#   - o "pronto p/ escrever" não é o genesis: é o RAFT eleger líder — polling
#     em http://baia_s:800s/status até algum coordinator responder
#     raft_leader=true (coordinator-s roda na baia s, porta host 8000+s).
# Params: RUNS, NODES, SUPERNODOS, SETTLE (espera pós-líder), READY_TIMEOUT.
# Uso: make cn-client-10runs-fresh RUNS=10 NODES=256 SUPERNODOS=4 [SETTLE=60]
cn-client-10runs-fresh:
	@command -v sshpass >/dev/null 2>&1 || { echo "ERRO: 'sshpass' não instalado (cn-stop apaga volumes via SSH com senha). Instale: sudo apt-get install -y sshpass"; exit 1; }
	@read -rs -p "Senha SSH ($(SSH_USER)@baias): " SSHPASS; echo; export SSHPASS; \
	svc=$(CN_STACK)_cottonclient; \
	BAIA_IPS_ARR=($(BAIA1_IP) $(BAIA2_IP) $(BAIA3_IP) $(BAIA4_IP)); \
	echo "══ CN fresh-ledger — $(RUNS) run(s), NODES=$(NODES) SN=$(SUPERNODOS) (rede recriada por run) ══"; \
	for i in $$(seq 1 $(RUNS)); do \
	  echo "──────── run $$i/$(RUNS) ────────"; \
	  echo "   [1/5] cn-stop (remove stack + volumes via SSH)"; \
	  $(MAKE) --no-print-directory cn-stop SSH='sshpass -e ssh -o StrictHostKeyChecking=accept-new' || { echo "   cn-stop falhou (senha?)"; exit 1; }; \
	  echo "   [2/5] cn-config (NODES=$(NODES), SUPERNODOS=$(SUPERNODOS))"; \
	  $(MAKE) --no-print-directory cn-config NODES=$(NODES) SUPERNODOS=$(SUPERNODOS) >/dev/null || { echo "   cn-config falhou"; exit 1; }; \
	  echo "   [3/5] cn-deploy-seq (genesis por SN)"; \
	  $(MAKE) --no-print-directory cn-deploy-seq NODES=$(NODES) SUPERNODOS=$(SUPERNODOS) || { echo "   cn-deploy-seq falhou"; exit 1; }; \
	  docker service update --restart-condition none --detach $$svc >/dev/null 2>&1 || true; \
	  echo "   [4/5] aguardando líder RAFT (até $(READY_TIMEOUT)s)"; \
	  t=0; lider=""; \
	  until [ -n "$$lider" ]; do \
	    for s in $$(seq 1 $(SUPERNODOS)); do \
	      ip=$${BAIA_IPS_ARR[$$((s-1))]}; \
	      curl -sf --max-time 5 "http://$$ip:$$((8000+s))/status" 2>/dev/null \
	        | grep -Eq '"raft_leader": ?true' && { lider="coordinator-$$s"; break; }; \
	    done; \
	    [ -n "$$lider" ] && break; \
	    sleep 5; t=$$((t+5)); [ $$t -ge $(READY_TIMEOUT) ] && { echo "   timeout esperando líder RAFT"; exit 1; }; \
	  done; \
	  echo "   líder RAFT: $$lider; estabilizando $(SETTLE)s..."; sleep $(SETTLE); \
	  echo "   [5/5] client run $$i"; \
	  prev=$$(docker service ps $$svc -q --no-trunc 2>/dev/null | head -1); \
	  docker service scale --detach $$svc=1 >/dev/null; \
	  until cur=$$(docker service ps $$svc -q --no-trunc 2>/dev/null | head -1); \
	        [ -n "$$cur" ] && [ "$$cur" != "$$prev" ]; do sleep 2; done; \
	  echo "      task $${cur:0:12} rodando; aguardando concluir..."; \
	  while :; do \
	    st=$$(docker service ps $$svc --no-trunc --format '{{.CurrentState}}' 2>/dev/null | head -1); \
	    case "$$st" in \
	      Complete*) echo "      run $$i OK ($$st)"; break ;; \
	      Failed*|Rejected*) echo "      run $$i FALHOU: $$st"; docker service scale --detach $$svc=0 >/dev/null 2>&1 || true; exit 1 ;; \
	      *) sleep $(POLL) ;; \
	    esac; \
	  done; \
	  docker service scale --detach $$svc=0 >/dev/null 2>&1 || true; \
	  csv=$$(ls -t $(RESULTS_DIR)/*.csv 2>/dev/null | head -1); \
	  if [ -n "$$csv" ]; then python3 scripts/analyze_metrics.py "$$csv" --md "$${csv%.csv}.report.md" >/dev/null 2>&1 || echo "      [aviso] analyze_metrics falhou"; fi; \
	done; \
	echo "══ concluído: $(RUNS) run(s) CN fresh-ledger. CSVs+reports em $(RESULTS_DIR) ══"

cn-logs-client:
	docker service logs -f $(CN_STACK)_cottonclient

cn-logs-coord:
	docker service logs -f $(CN_STACK)_coordinator-$(NODE)


.PHONY: help swarm-init registry-start \
        von-config von-patch von-patch-scale von-local-build von-local-start von-local-stop \
        von-start von-stop von-status \
        build push client-push deploy teardown client-start client-stop \
        client-10runs logs-client logs-coord status experiment \
        ct-config ct-deploy ct-stop ct-status ct-genesis \
        ct-client-start ct-client-stop ct-client-10runs ct-client-10runs-fresh \
        cn-client-10runs-fresh \
        ct-logs-node \
        ct-logs-client ct-logs-web \
        cn-config cn-deploy cn-deploy-seq cn-stop cn-status cn-genesis \
        cn-client-start cn-client-stop cn-client-10runs cn-logs-client cn-logs-coord
