# Deploy
The ivcap crew ai service deployment is controlled by lambda service controller, and the service description should be found at ./deploy/service.json.

## Deploy to develop
It automatically triggered when push/merge to main branch, with short SHA of HEAD commit as version

## Deploy to prod
It triggered by pushing tag, and the version is the tag, the tag must be in the form of `va.b.c`
For example:
```
git checkout main (or a commit which you want to tag, if not the HEAD of main branch)
git tag v0.0.1
git push origin tag v0.0.1
```

## Authentication
The github workflow utilise OIDC for cloud build.
*The repo needs to be added into the allowed list in ivcap-works/ivcap-infra*