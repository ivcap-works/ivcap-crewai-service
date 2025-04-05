SERVICE_NAME=crew-ai-service
SERVICE_TITLE=Execute a crewAI instruction set

# SERVICE_FILE=crew_ai_service.py
# PROVIDER_NAME=sc.experimental
IVCAP_SERVICE_FILE=service.json

include Makefile.common

RUN_DIR = ${PROJECT_DIR}/_run_

TMP_DIR=/tmp
PORT=8077
SERVICE_URL=http://localhost:8077

run:
	env VERSION=$(VERSION) \
		IVCAP_BASE_URL=https://develop.ivcap.net \
		python ${PROJECT_DIR}/service.py --port ${PORT}

TEST_REQUEST=crews/simple_crew.json
test-local:
	curl \
		-X POST \
		-H "Timeout: 600" \
		-H "content-type: application/json" \
		--data @${TEST_REQUEST}  \
		http://localhost:${PORT} | jq

TEST_REQUEST=crews/simple_crew.json
test-local-with-auth:
	TOKEN=$(shell ivcap --context gke-dev context get access-token --refresh-token); \
	curl \
		-X POST \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Timeout: 600" \
		-H "content-type: application/json" \
		--data @${TEST_REQUEST}  \
		http://localhost:${PORT} | jq

TEST_SERVER=http://ivcap.minikube

test-job:
	curl  -i  \
		-X POST \
		-H "Authorization: Bearer $(shell ivcap context get access-token --refresh-token)"  \
		-H "Content-Type: application/json" \
		-H "Timeout: 60" \
		--data @${TEST_REQUEST} \
		${TEST_SERVER}/1/services2/${SERVICE_ID}/jobs

test-job-ivcap:
	TOKEN=$(shell ivcap context get access-token --refresh-token); \
	curl -i -X POST \
	-H "content-type: application/json" \
	-H "Timeout: 2" \
	-H "Authorization: Bearer $$TOKEN" \
	--data @${TEST_REQUEST} \
	$(shell ivcap context get url)/1/services2/${SERVICE_ID}/jobs

JOB_ID=00000000-0000-0000-0000-000000000000
test-get-result-ivcap:
	TOKEN=$(shell ivcap context get access-token --refresh-token); \
	curl \
	-H "content-type: application/json" \
	-H "Timeout: 20" \
	-H "Authorization: Bearer $$TOKEN" \
	$(shell ivcap context get url)/1/services2/${SERVICE_ID}/jobs/${JOB_ID}?with-result-content=true | jq

submit-request:
	curl -X POST -H "Content-Type: application/json" -d @${PROJECT_DIR}/examples/simple_crew.json ${SERVICE_URL}

build:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

clean:
	rm -rf ${RUN_DIR}
	rm -rf db
	rm log.txt

docker-run: #docker-build
	mkdir -p ${RUN_DIR} && rm -rf ${RUN_DIR}/*
	docker run -it \
		-p ${PORT}:${PORT} \
		--platform=linux/${TARGET_ARCH} \
		-e IVCAP_BASE_URL=https://develop.ivcap.net \
		--rm \
		${DOCKER_NAME}_${TARGET_ARCH} --port ${PORT}

docker-debug: #docker-build
	# If running Minikube, the 'data' directory needs to be created inside minikube
	mkdir -p ${DOCKER_LOCAL_DATA_DIR}/in ${DOCKER_LOCAL_DATA_DIR}/out
	docker run -it \
		-e IVCAP_INSIDE_CONTAINER="" \
		-e IVCAP_ORDER_ID=ivcap:order:0000 \
		-e IVCAP_NODE_ID=n0 \
		-v ${PROJECT_DIR}:/data\
		--user ${DOCKER_USER} \
		--entrypoint bash \
		${DOCKER_TAG_LOCAL}

# docker-build:
# 	@echo "Building docker image ${DOCKER_NAME}"
# 	@echo "====> DOCKER_REGISTRY is ${DOCKER_REGISTRY}"
# 	@echo "====> LOCAL_DOCKER_REGISTRY is ${LOCAL_DOCKER_REGISTRY}"
# 	@echo "====> TARGET_PLATFORM is ${TARGET_PLATFORM}"
# 	DOCKER_BUILDKIT=1 docker build \
# 		-t ${DOCKER_NAME} \
# 		--platform=${TARGET_PLATFORM} \
# 		--build-arg GIT_COMMIT=${GIT_COMMIT} \
# 		--build-arg GIT_TAG=${GIT_TAG} \
# 		--build-arg BUILD_DATE="$(shell date)" \
# 		-f ${PROJECT_DIR}/Dockerfile \
# 		${PROJECT_DIR} ${DOCKER_BILD_ARGS}
# 	@echo "\nFinished building docker image ${DOCKER_NAME}\n"

# docker-run-data-proxy: #docker-build
# 	rm -rf /tmp/order1
# 	mkdir -p /tmp/order1/in
# 	mkdir -p /tmp/order1/out
# 	docker run -it \
# 		-e IVCAP_INSIDE_CONTAINER="Yes" \
# 		-e IVCAP_ORDER_ID=ivcap:order:0000 \
# 		-e IVCAP_NODE_ID=n0 \
# 		-e http_proxy=http://192.168.0.226:9999 \
# 	  -e https_proxy=http://192.168.0.226:9999 \
# 		-e IVCAP_STORAGE_URL=http://artifact.local \
# 	  -e IVCAP_CACHE_URL=http://cache.local \
# 		${DOCKER_NAME} \
# 		--crew urn:ivcap:artifact:16837369-e7ee-4f38-98cd-d2d056f5e148 \
# 		--p1 recycling \
# 		--p2 "plastics in ocean"

FORCE: run
.PHONY: run
