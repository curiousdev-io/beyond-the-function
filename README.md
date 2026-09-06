# beyond-the-function

Companion code for the [curiousdev.io](https://blog.curiousdev.io) posts on running containers past the point where a single function stops being the answer.

| Directory | Function |
| --- | --- |
| [`deploy-ecs-fargate/`](deploy-ecs-fargate/) | This project uses AWS CloudFormation to deploy a container image and a Flask application and it as a load-balanced service on Amazon ECS Fargate. |
| [`shared/`](shared/) | CloudFormation that more than one example needs |

Each blog post will have a supporting code directory. Each is self-contained apart from `shared/`, and each has its own `README`, its own `mise.toml`, and its own tasks.

## Prerequisites

**[mise](https://mise.jdx.dev) is the one tool you install yourself.** Everything else each example needs — language runtimes, the AWS CLI — is pinned in a `mise.toml` and installed by `mise`, so this is the only version that depends on what is already on your machine:

```bash
brew install mise           # macOS
curl https://mise.run | sh  # everything else
```

Then trust the config and install the toolchain:

```bash
mise trust                       # once per clone, at the repo root
mise install                     # shared tooling (the AWS CLI)

cd deploy-ecs-fargate
mise trust                       # each example has its own config
mise install                     # that example's runtime
mise tasks                       # what you can run
```

The project configuration is layered. The root `mise.toml` holds tooling every example needs, and each example's `mise.toml` adds its own. mise merges the parent into the child, so running tasks from inside an example gives you both.

Depending on which example you are running, you may also need Docker and AWS credentials. Check the `README` of each example.

## Conventions

- **Root is shared, subdirectories are examples.** A template used by more than one example lives in `shared/`; anything specific to one example lives with it.

- **Mise tasks are shell scripts** so they can be read, run, and reviewed like any other code.
