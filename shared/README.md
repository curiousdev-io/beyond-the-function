# Shared templates

CloudFormation that more than one example needs. Everything here is generic and
parameterised; anything specific to a single example belongs in that example's
directory instead.

| File | What it is |
| --- | --- |
| `ecr-repository.yaml` | ECR repository, lifecycle policy, scan on push |

A shared template does not mean a shared stack. Each example deploys its own
stack under its own name — the repository is named after `ProjectName` and the
exports are keyed on `AWS::StackName` — so two examples never collide, and
tearing one down leaves the others alone.

Before changing anything here, check who else uses it:

```bash
grep -rn "shared/" --include='*.md' --include='deploy-ecr' ..
```
