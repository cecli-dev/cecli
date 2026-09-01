---
parent: Usage
nav_order: 901
description: Use cecli to edit configuration files, documentation, and other text-based formats.
---


# Editing config & text files

Cecli isn't just for code, it can be very helpful when editing almost any text file. You can use cecli to make changes to your shell & ssh settings, Dockerfiles or pretty much any configuration or documentation file.

Here are some practical examples of modifying common config/text files:

## Shell Configuration

$ cecli .bashrc

Added .bashrc to the chat.


#### Add an alias 'll' that lists all files, with all details in human readable format. And update PATH to include uv installed tools.

```
+ alias ll='ls -alh'
+ export PATH="$PATH:$HOME/.local/bin:$PATH"
```

## SSH Configurations

$ cecli ~/.ssh/config

Added config to the chat.

#### Create a Host entry 'my-server' using bastion.example.com as JumpHost

```
+ Host my-server
+     HostName 192.168.1.100
+     User deploy
+     Port 2222
+     IdentityFile ~/.ssh/deploy_key
+     ProxyJump bastion.example.com
```

## Docker Setup

$ cecli Dockerfile docker-compose.yml

Added Dockerfile and docker-compose.yml to the chat.

#### Set non-root user and enable healthchecks

```
+ USER appuser
+ HEALTHCHECK --interval=30s --timeout=3s \
+   CMD curl -f http://localhost:8000/health || exit 1
```

#### Expose port 5432 and add volume for postgres data

```
  services:
    postgres:
      image: postgres:15
+     ports:
+       - "5432:5432"
+     volumes:
+       - pgdata:/var/lib/postgresql/data
```

## Git Configuration

$ cecli .gitconfig

Added .gitconfig to the chat.

#### Set default push behavior to current branch and enable color UI

```
+ [push]
+     default = current
+ [color]
+     ui = auto
```

## System Configuration
$ cecli /etc/hosts  # May need sudo

Added hosts to the chat.

#### Block tracking domains by pointing them to 127.0.0.1

```
+ 127.0.0.1   ads.example.com
+ 127.0.0.1   track.analytics.co
```


## Editor Configs
$ cecli .vimrc

Added .vimrc to the chat.

#### Enable line numbers and set 4-space tabs for Python

```
+ set number
+ autocmd FileType python set tabstop=4 shiftwidth=4 expandtab
```

## VSCode Configuration
$ cecli settings.json

Added settings.json to the chat.

#### Enable auto-format on save and set default formatter

```
+ "editor.formatOnSave": true,
+ "editor.defaultFormatter": "esbenp.prettier-vscode"
```

## Markdown Documentation
$ cecli README.md

Added README.md to the chat.


#### Add installation section with brew and pip options

```
+ ## Installation
+ ```
+ # Homebrew
+ brew install cool-app-10k
+ 
+ # PyPI
+ pipx install cool-app-10k
+ ```
```

## XML Configuration
$ cecli pom.xml

Added pom.xml to the chat.
#### Add JUnit 5 dependency with test scope

```
+ <dependency>
+     <groupId>org.junit.jupiter</groupId>
+     <artifactId>junit-jupiter-api</artifactId>
+     <version>5.9.2</version>
+     <scope>test</scope>
+ </dependency>
```


