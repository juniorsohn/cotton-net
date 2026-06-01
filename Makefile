# COTTONTRUST / COTTON-NET — Makefile
#
# Workflow de um experimento:
#   1. make swarm-init            (uma vez só)
#   2. make von-start NODES=32    (varia entre experimentos)
#   3. make deploy
#   4. make logs-client
#   5. make teardown && make von-stop
#   6. Repete a partir do passo 2 com NODES diferente

NODES      ?= 32
SUPERNODOS ?= 4
STACK      ?= cottontrust
SSH_USER   ?= indy
VON_DIR    ?= /home/indy/von-network

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
REGISTRY   ?= $(BAIA1_IP):5000

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
	@echo "  von-local-start         Rebuild + start-combined na baia atual"
	@echo "  von-local-stop          Para o supernodo local"
	@echo "  von-start   NODES=N     von-config + instrução para cada baia"
	@echo "  von-stop                Para todos os VON Networks via SSH"
	@echo "  von-status              Verifica genesis endpoints"
	@echo "  build                   Constrói imagens Docker"
	@echo "  push                    Envia imagens para $(REGISTRY)"
	@echo "  deploy                  Deploy do stack no Swarm"
	@echo "  teardown                Remove o stack"
	@echo "  logs-client             Logs do cottonclient"
	@echo "  logs-coord NODE=N       Logs do coordinator-N"
	@echo "  status                  Status do stack"
	@echo "  experiment NODES=N      von-start + deploy de uma vez"
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

von-local-start:
	@# Roda na baia atual: rebuild + ./manage start <IP local>
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
	docker build -t $(REGISTRY)/cottontrust-client:latest     -f client/dockerfile .
	docker build -t $(REGISTRY)/cottontrust-coordinator:latest -f coordinator/dockerfile .

push: build
	docker push $(REGISTRY)/cottontrust-client:latest
	docker push $(REGISTRY)/cottontrust-coordinator:latest

deploy:
	docker stack deploy -c docker-compose.yml $(STACK)

teardown:
	docker stack rm $(STACK)

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
	@echo "Monitoramento: http://$(BAIA5_IP):3000"
	@echo "Prometheus:    http://$(BAIA5_IP):9090"

.PHONY: help swarm-init registry-start von-start von-stop von-status \
        build push deploy teardown logs-client logs-coord status experiment
