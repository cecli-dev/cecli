---
parent: Installation
nav_order: 100
---

# cecli with docker

Cecli is available as a docker image:

- `dustinwashington/cecli` installs the cecli core, a smaller image that's good to get started quickly.

### Aider core 

```bash
docker pull dustinwashington/cecli
docker run \
  -it \
  --user $(id -u):$(id -g) \
  --volume $(pwd):/app dustinwashington/cecli \
  --volume $(pwd)/.aider.conf.yml:/.aider.conf.yml \
  --volume $(pwd)/.aider.env:/.aider/.env \
  [...other args...] \
  --config /app/.aider.conf.yml 
```

## How to use it

You should run the above commands from the root of your git repo,
since the `--volume` arg maps your current directory into the
docker container.
Given that, you need to be in the root of your git repo for aider to be able to
see the repo and all its files.

You should be sure your that
git repo config contains your user name and email, since the
docker container won't have your global git config.
Run these commands while in your git repo, before
you do the `docker run` command:

```
git config user.email "you@example.com"
git config user.name "Your Name"
```

## Limitations

- When you use the in-chat `/run` command, it will be running shell commands *inside the docker container*. So those commands won't be running in your local environment, which may make it tricky to `/run` tests, etc for your project.
- The `/voice` command won't work unless you can figure out how to give the docker container access to your host audio device. The container has libportaudio2 installed, so it should work if you can do that.
