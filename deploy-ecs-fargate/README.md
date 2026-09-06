# ECS Fargate demo

This repository contains companion code for [Zero to Running Task: Your First ECS Service](https://blog.curiousdev.io/zero-to-running-task).

This project uses AWS CloudFormation to deploy a container image and a Flask application and it as a load-balanced service on Amazon ECS Fargate.

> [!WARNING]
> **This demo costs money to run, and the meter keeps running until you delete it.**
>
> **When you are done, run `mise nuke-fargate-demo`.** See [Tearing down](#tearing-down) for what it removes and what it deliberately leaves behind.

| File | What it is |
| --- | --- |
| `app.py` | Flask app with `/hello`, `/goodbye`, and `/health` routes |
| `log_config.py` | JSON log formatter, standard library only |
| `gunicorn_logging.py` | gunicorn access logger that emits fields, not a formatted string |
| `gunicorn.conf.py` | Bind address, workers, and logging, for the image and local runs alike |
| `Dockerfile` | Container image, non-root, gunicorn on port 8080 |
| `requirements.txt` | Flask and gunicorn, pinned |
| `requirements-dev.txt` | The above plus pytest. Not installed into the image. |
| `mise.toml` | Python version and the tasks below |
| `tests/` | Unit tests |
| `../shared/ecr-repository.yaml` | The registry. Deploy first. Shared with the other examples. |
| `ecs-fargate.yaml` | Cluster, task definition, ALB, security groups, IAM roles, service |

## Tooling

[mise](https://mise.jdx.dev) pins the toolchain and carries the tasks. The
repo-root `mise.toml` pins the AWS CLI, because every example needs it; this
directory's `mise.toml` pins the Python version and everything specific to this
example. Task bodies are plain shell scripts in `mise-tasks/`, so you can read
them, run them, or lift them without mise in the way.

### Prerequisites

**mise is the one thing you have to install yourself.** Everything else —
Python, the AWS CLI — is pinned in config and installed by mise, so this is the
only version that depends on what is already on your machine:

```bash
brew install mise           # macOS
curl https://mise.run | sh  # everything else
```

Then, from this directory:

```bash
mise trust                 # required once
mise install               # the pinned tools: python and the aws cli
mise install-python-deps   # create .venv and install this project's dependencies
mise tasks                 # everything you can run
```

Those two installs are different jobs, which is why the task is not simply called `install`: `mise install` is mise's own command and installs the *tools* pinned in `mise.toml`, while `install-python-deps` is a task in this project that fills the virtualenv from `requirements-dev.txt`. The built-in wins the bare name, so the task says what it actually does.

You also need **Docker** for `docker-push`, and AWS credentials with permission to create ECR, ECS, ELB, IAM, and CloudWatch Logs resources.

Everything below runs through `mise`, which does not require mise to be activated in your shell. If you want the pinned `python` and `aws` on your `PATH` directly, add `mise activate` to your shell profile as the install output describes.

| Task | What it does |
| --- | --- |
| `mise install-python-deps` | Create `.venv` and install `requirements-dev.txt` |
| `mise test` | Run the unit tests. Extra args reach pytest: `mise test -- -k goodbye` |
| `mise run-local` | Serve on localhost under gunicorn, with `--reload` |
| `mise deploy-ecr` | Deploy the registry stack |
| `mise docker-push` | Build for the right architecture and push to ECR |
| `mise deploy` | Deploy the service stack |
| `mise smoke` | Exercise every route against the deployed load balancer |
| `mise url` | Print the service URL |
| `mise logs` | Tail the CloudWatch log group |
| `mise events` | Show failed AWS CloudFormation stack events, oldest first |
| `mise nuke-fargate-demo` | Destroy the service stack. **Run this when you are done — it bills hourly.** See [Tearing down](#tearing-down) |

### Configuration

Nothing account-specific is committed to this repo — no account ids, VPC ids, or subnet ids appear in any file here. Everything comes from the environment. `mise.toml` supplies defaults that the environment overrides; the values that identify *your* account have no defaults at all, because a default would be wrong for everyone.

| Variable | Default | What it is |
| --- | --- | --- |
| `PROJECT_NAME` | `curiousdev-fargate-demo` | Names the AWS resources. `ECR_STACK_NAME` and `SERVICE_STACK_NAME` derive from it |
| `AWS_REGION` | `us-east-1` | Region for every task |
| `DOCKER_PLATFORM` | `linux/arm64` | Must match `CpuArchitecture` in the service template |
| `IMAGE_TAG` | current commit SHA | Tag to build, push, and deploy |
| `ASSIGN_PUBLIC_IP` | `ENABLED` | Whether tasks get a public IP. See below |
| `VPC_ID` | **none — required** | The VPC to deploy into |
| `PUBLIC_SUBNET_IDS` | **none — required** | Comma-separated, for the load balancer |
| `TASK_SUBNET_IDS` | **none — required** | Comma-separated, where the tasks run |

Export the required three, or put them in a `mise.local.toml` of your own, which is gitignored:

```bash
export VPC_ID=vpc-...
export PUBLIC_SUBNET_IDS=subnet-...,subnet-...
export TASK_SUBNET_IDS=subnet-...,subnet-...
```

`PROJECT_NAME` is the single knob for naming. It names the cluster, the service, the task family, the log group `/ecs/<name>`, `<name>-alb`, `<name>-tg`, and the `<name>-execution` and `<name>-task` IAM roles; the two stack names derive from it so they cannot drift apart. It has to be unique per **account**, not per region — load balancer and target group names are regional, but IAM role names are global, so the same `PROJECT_NAME` in two regions collides.

The Python version in `mise.toml` tracks the tag in the `Dockerfile`. If you pin a patch version in one, pin it in the other; a local interpreter that does not match the image is the drift this is there to prevent.

## VPC requirements

`mise deploy` checks all of this before it calls CloudFormation, because every one of these failures either goes uncaught or surfaces twenty minutes later as a service that never stabilises.

**The load balancer needs two availability zones.** `PUBLIC_SUBNET_IDS` must name subnets in at least two different AZs. One AZ and the stack refuses to create.

**Every subnet must belong to `VPC_ID`.** Mixing in a subnet from another VPC produces a genuinely baffling failure message.

**The tasks must be able to reach ECR and CloudWatch Logs.** This is the one that decides whether the first deploy works, and there are exactly three workable answers for `TASK_SUBNET_IDS`:

| Subnet routing | `ASSIGN_PUBLIC_IP` | Result |
| --- | --- | --- |
| Private, NAT gateway | `DISABLED` | The right answer |
| Private, `ecr.api` + `ecr.dkr` + `logs` interface endpoints (and the S3 gateway endpoint) | `DISABLED` | Also correct, and cheaper than NAT for one service |
| Public, routes to an internet gateway | `ENABLED` | Works. The tasks are still not reachable from the internet — the security group only accepts traffic from the load balancer |
| Private, neither NAT nor endpoints | either | `CannotPullContainerError`. The most common failure |
| Public, routes to an internet gateway | `DISABLED` | No route out. Same `CannotPullContainerError` |

A public subnet with `ASSIGN_PUBLIC_IP=DISABLED` is the trap worth naming: the subnet has a route to the internet, but a Fargate task without a public IP has no way to use it. The task sits in `PENDING`, fails to pull, and the message says nothing about networking.

Note that `MapPublicIpOnLaunch` on the subnet is irrelevant here — Fargate takes the public IP setting from the service's network configuration, not from the subnet.

## The Application

Two greeting routes, each taking an optional `name` query parameter that defaults to `World`:

```
GET /hello?name=curiousdev    -> {"message": "Hello, curiousdev!",   "route": "hello"}
GET /goodbye?name=curiousdev  -> {"message": "Goodbye, curiousdev!", "route": "goodbye"}
GET /health              -> {"status": "ok"}
```

Run it locally:

```bash
mise run-local

curl "http://localhost:8080/hello?name=curiousdev"
curl "http://localhost:8080/goodbye"
```

That serves the app under gunicorn with the same config file the image uses, so the output you read locally is the output you will read in CloudWatch.

The default port matches the container's, which has to stay 8080 to line up with the task definition and the target group. 8080 is a busy port on a developer machine, so if something else already has it, use another:

```bash
PORT=8081 mise run-local
```

Test it:

```bash
mise test
```

## Logs

Everything the container writes to stdout is a single line of JSON: gunicorn's startup and shutdown messages, its access log, and the application's own events.

```json
{"timestamp": "2026-09-05T13:36:35.028+00:00", "level": "INFO", "logger": "app", "message": "greeting issued",  "request_id": "Root=1-abc-container", "event": "greeting", "route": "hello", "greeted": "Brian"}
```

This matters because of where the logs end up. The `awslogs` driver ships stdout to CloudWatch, and Logs Insights parses a JSON line into queryable fields for free:

```
fields @timestamp, request_id, route, greeted
| filter event = "greeting"
| sort @timestamp desc
```

With plain text you would be writing regexes against your own log format forever. Two consequences worth knowing:

- **One event per line.** A multi-line record is ingested as several unrelated  events, so tracebacks are escaped into a single `exception` field rather than printed raw.

- **`request_id` ties the lines together.** The ALB stamps `X-Amzn-Trace-Id` on every request it forwards; the app reuses it, and the access log carries it too, so one request's application lines, its access record, and the load balancer's own record all share an id. Running locally there is no ALB, so the app generates one per request instead.

`/health` deliberately writes no application log line — the target group polls it every few seconds per task, forever, and storing that buys you nothing. The access log still records it, which is where to look to prove the health checks are arriving.

Set `LOG_LEVEL` to change verbosity; it defaults to `INFO`.

## Deploying

You need a VPC with at least two subnets in different availability zones, and somewhere for the tasks to run. Read the note on `TaskSubnetIds` before you pick subnets.

Each step below is spelled out as the raw AWS CLI command, because knowing what the tooling is doing is most of the point. Each one also has a task — `mise deploy-ecr`, `docker-push`, `deploy`, `url` — which is what you will actually reach for on the second run. The tasks tag images with the commit SHA rather than `latest`, for the reason in "Redeploying after a code change".

Everything from here on costs money for as long as it exists. See the warning at the top, and [Tearing down](#tearing-down) when you are finished.

### 1. Create the registry

```bash
aws cloudformation deploy \
  --stack-name "${PROJECT_NAME}-ecr" \
  --template-file ../shared/ecr-repository.yaml \
  --parameter-overrides ProjectName="$PROJECT_NAME"
```

That template lives in [`../shared/`](../shared/) because every ECS example here needs a registry and the template is generic. Each example still deploys its *own* stack under its own name, so the images and the stack exports stay separate and one example can be torn down without touching another.

This stack is separate on purpose. A service cannot start without an image, and an empty repository cannot produce one, so a combined template fails its first deploy every time: repository created, tasks cannot pull, circuit breaker trips, rollback deletes the repository. Registries also outlive the services they feed.

### 2. Build and push the image

```bash
REPO=$(aws cloudformation describe-stacks \
  --stack-name "${PROJECT_NAME}-ecr" \
  --query 'Stacks[0].Outputs[?OutputKey==`RepositoryUri`].OutputValue' \
  --output text)

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${REPO%%/*}"

# --platform must match CpuArchitecture in the service template.
docker buildx build --platform "$DOCKER_PLATFORM" -t "${REPO}:${IMAGE_TAG}" --push .
```

If you set `CpuArchitecture=X86_64` in step 3, build `--platform linux/amd64` instead. A mismatch produces a task that dies immediately with an exec format error.

### 3. Deploy the service

```bash
aws cloudformation deploy \
  --stack-name "$PROJECT_NAME" \
  --template-file ecs-fargate.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      ProjectName="$PROJECT_NAME" \
      VpcId="$VPC_ID" \
      PublicSubnetIds="$PUBLIC_SUBNET_IDS" \
      TaskSubnetIds="$TASK_SUBNET_IDS" \
      AssignPublicIp="$ASSIGN_PUBLIC_IP" \
      EcrStackName="${PROJECT_NAME}-ecr" \
      ImageTag="$IMAGE_TAG"
```

`CAPABILITY_NAMED_IAM` rather than `CAPABILITY_IAM`, because the template names its roles. The service stack imports the repository URI from the ECR stack's exports, so nothing has to paste an account ID around.

Two of these are worth passing explicitly rather than letting the template's defaults apply:

- **`ProjectName`** names the cluster, the roles, the load balancer, and the log group. Leave it out and you get a stack whose resources are all named after the template's default instead — silently, with no error.

- **`AssignPublicIp`** defaults to `DISABLED`, which is right for private subnets and wrong for public ones. See "VPC requirements".

### 4. Try it

```bash
URL=$(aws cloudformation describe-stacks \
  --stack-name "$PROJECT_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`ServiceUrl`].OutputValue' \
  --output text)

curl "$URL/hello?name=Brian"
curl "$URL/goodbye?name=Brian"
```

Alternatively, let `mise smoke` do it, which finds the load balancer from the stack
output, hits every route, and checks what came back:

```bash
mise smoke                      # greets "World"
mise smoke -- Brian             # greets "Brian"
mise smoke -- "Ada Lovelace"    # spaces and & are encoded properly
NAME=Brian mise smoke           # same, from the environment
```

```
Exercising http://curiousdev-fargate-demo-alb-XXXXXXXXX.us-east-1.elb.amazonaws.com
Greeting as "Brian"

  GET /health                        200   {"status":"ok"}
  GET /                              200   {"routes":[...],"service":"ecs-fargate-demo"}
  GET /hello                         200   {"message":"Hello, Brian!","route":"hello"}
  GET /goodbye                       200   {"message":"Goodbye, Brian!","route":"goodbye"}
  GET /nope (404)                    404   {"error":"not found","routes":[...]}

5 passed
```

It exits non-zero if any route misbehaves, so it works in a pipeline as well as by hand. Each check compares the HTTP status and one field of the JSON body rather than the whole thing, so adding a key to a response does not break it.
`/nope` is in there deliberately: the 404 handler returning JSON instead of werkzeug's HTML page is a feature, and worth catching a regression in.

This is a different job from `mise test`. The unit tests run against the code in this directory and need nothing deployed; `smoke` runs against whatever is actually live in AWS, which is the only way to catch a stale image, a broken target group, or a task that is running but unreachable.

## Redeploying after a code change

Pushing a new image to the same `:latest` tag does **not** update the service.
CloudFormation compares templates, the template did not change, so nothing
happens. Either force a new deployment:

```bash
aws ecs update-service \
  --cluster "$PROJECT_NAME" \
  --service "$PROJECT_NAME" \
  --force-new-deployment
```

...or, better, tag images with the commit SHA and pass `ImageTag=$(git rev-parse --short HEAD)`.
Then the template genuinely changes, and you get a real rollback target.

## When it doesn't work

| Symptom | Look here first |
| --- | --- |
| Task stuck in `PENDING`, then stops | Execution role permissions, or no route to ECR from the task subnets |
| `CannotPullContainerError` | Subnet routing, then the image tag |
| `exec format error` | Built for the wrong architecture |
| Tasks running, ALB says unhealthy | `/health` not answering 200, or the wrong container port |
| Tasks start and die in a loop | Health check grace period too short, or the app is crashing. Read the logs. |
| Stack fails before creating anything | Missing `CAPABILITY_NAMED_IAM` |
| Stack stuck in `CREATE_IN_PROGRESS` 20+ minutes | The service never stabilized |
| `No export named ...-RepositoryUri` | The ECR stack is not deployed, or `EcrStackName` is wrong |

Read stack events oldest-first and trust the first failure; the rest are
consequences:

```bash
aws cloudformation describe-stack-events \
  --stack-name "$PROJECT_NAME" \
  --query 'reverse(StackEvents[?ResourceStatus==`CREATE_FAILED`].[LogicalResourceId,ResourceStatusReason])' \
  --output text
```

For a task that started and then stopped, ECS tells you exactly why:

```bash
aws ecs describe-tasks \
  --cluster "$PROJECT_NAME" \
  --tasks <task-id> \
  --query 'tasks[0].stoppedReason'
```

Logs and a shell:

```bash
aws logs tail "/ecs/${PROJECT_NAME}" --follow

aws ecs execute-command \
  --cluster "$PROJECT_NAME" \
  --task <task-id> \
  --container app \
  --interactive \
  --command "/bin/sh"
```

A stack in `ROLLBACK_COMPLETE` cannot be updated. Delete it and deploy again.

## Tearing down

The load balancer and the Fargate tasks bill for as long as they exist, so tear the demo down when you are finished with it:

```bash
mise nuke-fargate-demo
```

It shows you what is about to go, including how many tasks are currently
running, and then asks you to type the stack name before it does anything:

```
About to destroy stack: curiousdev-fargate-demo
Region:                 us-east-1
Current status:         CREATE_COMPLETE

This deletes, and they stop billing:

  - the application load balancer, its listener and target group
    (billed per hour whether or not anything sends it traffic)
  - the ECS service and its 2 running task(s)
    (billed per task for vCPU and memory, by the second)
  - the ECS cluster, both IAM roles, both security groups,
    and the task definition
...
Type the stack name to confirm:
```

Anything other than the exact stack name aborts without deleting. It also
refuses to run non-interactively, so a script that invokes it by accident
cannot destroy a stack with nobody watching — `FORCE=1 mise nuke-fargate-demo`
is the deliberate override for a pipeline.

### What survives, and why

Deleting the service stack does **not** get you back to zero:

| Resource | Why it stays | Ongoing cost |
| --- | --- | --- |
| Log group `/ecs/$PROJECT_NAME` | `DeletionPolicy: Retain` — a teardown should not destroy the logs explaining why you tore it down | Storage only, pennies |
| ECR repository and images | Separate stack, and also `Retain` | Storage only |

Neither bills by the hour, so leaving them is usually the right call. The task
prints the exact commands to remove them too. Note that deleting the ECR
*stack* leaves the repository behind — that is what `Retain` means — so the
repository needs deleting explicitly:

```bash
aws logs delete-log-group --log-group-name "/ecs/${PROJECT_NAME}"
aws cloudformation delete-stack --stack-name "${PROJECT_NAME}-ecr"
aws ecr delete-repository --repository-name "$PROJECT_NAME" --force
```
