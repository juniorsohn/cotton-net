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
	@echo "  ct-logs-client          Logs do cottonclient"
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

deploy:
	docker stack deploy --resolve-image=never -c docker-compose.yml $(STACK)

teardown:
	docker stack rm $(STACK)

client-start:
	docker service scale $(STACK)_cottonclient=1

client-stop:
	docker service scale $(STACK)_cottonclient=0

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
	@echo "Removendo docker config (se existir)..."
	-docker config rm von-gen-tx-n$(NODES) 2>/dev/null || true
	@echo "Aguardando containers encerrarem..."
	@sleep 10
	@echo "Removendo volumes de ledger (cacao)..."
	-ssh $(SSH_USER)@$(BAIA5_IP) \
		"docker volume rm $(CT_STACK)_webserver-ledger $(CT_STACK)_webserver-cli \
		$(CT_STACK)_client-output $(CT_STACK)_client-wallets 2>/dev/null || true"
	@echo "Removendo volumes de nós (flores/corisco/baiacu/pernambuco)..."
	@for ip in $(BAIA1_IP) $(BAIA2_IP) $(BAIA3_IP) $(BAIA4_IP); do \
		ssh $(SSH_USER)@$$ip \
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

ct-logs-client:
	docker service logs -f $(CT_STACK)_cottonclient

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
	@echo "Aguardando containers e rede encerrarem..."
	@until ! docker network ls --format '{{.Name}}' | grep -q "^$(CN_STACK)_"; do \
		printf '.'; sleep 5; \
	done; echo " rede removida."
	@echo "Removendo docker configs..."
	@for s in $$(seq 1 $(SUPERNODOS)); do \
		docker config rm "cn-gen-tx-sn$${s}-kn$$(( $(NODES) / $(SUPERNODOS) ))"    2>/dev/null || true; \
		docker config rm "cn-start-node-sn$${s}-kn$$(( $(NODES) / $(SUPERNODOS) ))" 2>/dev/null || true; \
	done
	@echo "Removendo volumes das baias..."
	@for ip in $(BAIA1_IP) $(BAIA2_IP) $(BAIA3_IP) $(BAIA4_IP) $(BAIA5_IP); do \
		ssh $(SSH_USER)@$$ip \
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

cn-logs-client:
	docker service logs -f $(CN_STACK)_cottonclient

cn-logs-coord:
	docker service logs -f $(CN_STACK)_coordinator-$(NODE)


.PHONY: help swarm-init registry-start \
        von-config von-patch von-local-build von-local-start von-local-stop \
        von-start von-stop von-status \
        build push deploy teardown client-start client-stop \
        logs-client logs-coord status experiment \
        ct-config ct-deploy ct-stop ct-status ct-genesis \
        ct-client-start ct-client-stop ct-logs-client ct-logs-web \
        cn-config cn-deploy cn-deploy-seq cn-stop cn-status cn-genesis \
        cn-client-start cn-client-stop cn-logs-client cn-logs-coord
