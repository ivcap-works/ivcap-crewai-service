SERVICE_NAME=crew-ai-service

TMP_DIR=/tmp
PORT=8077
SERVICE_URL=http://localhost:8077
TIMEOUT=360

run:
	poetry ivcap run -- --port ${PORT}

TEST_REQUEST=crews/simple_crew.json
test-local:
	curl \
		-X POST \
		-H "Timeout: ${TIMEOUT}" \
		-H "content-type: application/json" \
		--data @${TEST_REQUEST}  \
		http://localhost:${PORT} | jq

TEST_REQUEST=crews/simple_crew.json
test-local-with-auth:
	TOKEN=$(shell ivcap context get access-token --refresh-token); \
	curl \
		-X POST \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Timeout: ${TIMEOUT}" \
		-H "content-type: application/json" \
		--data @${TEST_REQUEST}  \
		http://localhost:${PORT} | jq

TEST_SERVER=http://ivcap.minikube
SERVICE_ID=$(shell poetry ivcap --silent get-service-id)
test-job:
	curl  -i  \
		-X POST \
		-H "Authorization: Bearer $(shell ivcap context get access-token --refresh-token)"  \
		-H "Content-Type: application/json" \
		-H "Timeout: ${TIMEOUT}" \
		--data @${TEST_REQUEST} \
		${TEST_SERVER}/1/services2/${SERVICE_ID}/jobs

test-job-ivcap:
	poetry ivcap exec-job ${TEST_REQUEST} -- --stream

test-job-ivcap-curl:
	TOKEN=$(shell ivcap context get access-token --refresh-token); \
	curl -i -X POST \
	-H "content-type: application/json" \
	-H "Timeout: ${TIMEOUT}" \
	-H "Authorization: Bearer $$TOKEN" \
	--data @${TEST_REQUEST} \
	${TEST_SERVER}/1/services2/${SERVICE_ID}/jobs

JOB_ID=00000000-0000-0000-0000-000000000000
test-get-result-ivcap:
	TOKEN=$(shell ivcap context get access-token --refresh-token); \
	curl \
	-H "content-type: application/json" \
	-H "Timeout: 20" \
	-H "Authorization: Bearer $$TOKEN" \
	$(shell ivcap context get url)/1/services2/${SERVICE_ID}/jobs/${JOB_ID}?with-result-content=true | jq

test-get-result:
	curl  \
		-H "Authorization: Bearer $(shell ivcap context get access-token --refresh-token)"  \
		-H "Content-Type: application/json" \
		${TEST_SERVER}/1/services2/${SERVICE_ID}/jobs/${JOB_ID}?with-result-content=true | jq

test-get-result-raw:
	curl  -i -L \
		-H "Authorization: Bearer $(shell ivcap context get access-token --refresh-token)"  \
		-H "Content-Type: application/json" \
		${TEST_SERVER}/1/services2/${SERVICE_ID}/jobs/${JOB_ID}?with-result-content=true

test-get-events:
	curl  \
		--no-buffer \
		-H "Authorization: Bearer $(shell ivcap context get access-token --refresh-token)"  \
		-H "Accept: text/event-stream" \
		${TEST_SERVER}/1/services2/${SERVICE_ID}/jobs/${JOB_ID}/events

list-results-ivcap:
	TOKEN=$(shell ivcap context get access-token --refresh-token); \
	curl \
	-H "content-type: application/json" \
	-H "Timeout: 20" \
	-H "Authorization: Bearer $$TOKEN" \
	$(shell ivcap context get url)/1/services2/${SERVICE_ID}/jobs | jq

submit-request:
	curl -X POST -H "Content-Type: application/json" -d @${PROJECT_DIR}/examples/simple_crew.json ${SERVICE_URL}

build:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

clean:
	rm -rf ${RUN_DIR}
	rm -rf db
	rm log.txt

TARGET_ARCH=arm64
DOCKER_NAME=ivcap_crew_ai
DOCKER_VERSION=738762e
docker-run: #docker-build
	docker run -it \
		-p ${PORT}:${PORT} \
		--platform=linux/${TARGET_ARCH} \
		--rm \
		${DOCKER_NAME}_${TARGET_ARCH}:${DOCKER_VERSION} --port ${PORT}


FORCE: run
.PHONY: run
