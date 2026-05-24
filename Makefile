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
REGISTRY   ?= localhost:5000
SSH_USER   ?= indy
VON_DIR    ?= /home/indy/von-network

export REGISTRY SSH_USER VON_DIR

.DEFAULT_GOAL := help

help:
	@echo ""
	@echo "COTTONTRUST / COTTON-NET"
	@echo "════════════════════════════════════════"
	@echo "  swarm-init              Inicializa Docker Swarm"
	@echo "  registry-start          Sobe registry local em baia1:5000"
	@echo "  von-start  NODES=N      Inicia VON Networks (padrão: N=32)"
	@echo "  von-stop                Para todos os VON Networks"
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
	@ssh $(SSH_USER)@baia1 "docker run -d -p 5000:5000 --restart always \
		--name registry registry:2 2>/dev/null || echo '(já rodando)'"

von-start:
	@chmod +x scripts/start_von.sh
	@./scripts/start_von.sh $(NODES) $(SUPERNODOS)

von-stop:
	@chmod +x scripts/stop_von.sh && ./scripts/stop_von.sh

von-status:
	@for m in baia1 baia2 baia3 baia4; do \
		curl -sf http://$$m:9000/genesis > /dev/null \
			&& echo "  ✅ http://$$m:9000/genesis" \
			|| echo "  ❌ http://$$m:9000/genesis"; \
	done

build:
	docker build -t $(REGISTRY)/cottontrust-client:latest ./client
	docker build -t $(REGISTRY)/cottontrust-coordinator:latest ./coordinator

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
	@echo "Monitoramento: http://baia5:3000"
	@echo "Prometheus:    http://baia5:9090"

.PHONY: help swarm-init registry-start von-start von-stop von-status \
        build push deploy teardown logs-client logs-coord status experiment