---
parent: Installation
nav_order: 20
---

# Optional steps
{: .no_toc }

The steps below are completely optional.

- TOC
{:toc}

## Install git

cecli works best if you have git installed.
Here are
[instructions for installing git in various environments](https://github.com/git-guides/install-git).

## Setup an API key

You need an key from an API provider to work with most models:

- [OpenAI](https://help.openai.com/en/articles/4936850-where-do-i-find-my-secret-api-key) provides o1, o3-mini, gpt-4o and other models. Note that paying for an API key is different than being a "ChatGPT" subscriber.
- [Anthropic](https://docs.anthropic.com/claude/reference/getting-started-with-the-api) provides Claude 3.7 Sonnet and Haiku.
- [DeepSeek](https://platform.deepseek.com/api_keys) provides DeepSeek R1 and DeepSeek Chat V3.
- [OpenRouter](https://openrouter.ai/keys) allows you to access models from many providers using a single key.

You can [store your api keys in configuration or env files](/docs/config/api-keys.html)
and they will be loaded automatically whenever you run cecli.

## Enable Playwright 

cecli supports adding web pages to the chat with the `/web <url>` command.
When you add a url to the chat, cecli fetches the page and scrapes its
content.

By default, cecli uses the `httpx` library to scrape web pages, but this only
works on a subset of web pages.
Some sites explicitly block requests from tools like httpx.
Others rely heavily on javascript to render the page content,
which isn't possible using only httpx.

cecli works best with all web pages if you install
Playwright's chromium browser and its dependencies:

```
playwright install --with-deps chromium
```

See the
[Playwright for Python documentation](https://playwright.dev/python/docs/browsers#install-system-dependencies)
for additional information.


## Enable voice coding 

cecli supports 
[coding with your voice](https://cecli.dev/docs/usage/voice.html)
using the in-chat `/voice` command.
cecli uses the [PortAudio](http://www.portaudio.com) library to
capture audio.
Installing PortAudio is completely optional, but can usually be accomplished like this:

- For Windows, there is no need to install PortAudio.
- For Mac, do `brew install portaudio`
- For Linux, do `sudo apt-get install libportaudio2`
  - Some linux environments may also need `sudo apt install libasound2-plugins`

## Add cecli to your IDE/editor

You can use 
[cecli's `--watch-files` mode](https://cecli.dev/docs/usage/watch.html)
to integrate with any IDE or editor.

There are a number of 3rd party cecli plugins for various IDE/editors.
It's not clear how well they are tracking the latest
versions of cecli,
so it may be best to just run the latest
cecli in a terminal alongside your editor and use `--watch-files`.

### NeoVim

[joshuavial](https://github.com/joshuavial) provided a NeoVim plugin for cecli:

[https://github.com/joshuavial/cecli.nvim](https://github.com/joshuavial/cecli.nvim)

### VS Code

You can run cecli inside a VS Code terminal window.
There are a number of 3rd party 
[cecli plugins for VSCode](https://marketplace.visualstudio.com/search?term=cecli%20-kodu&target=VSCode&category=All%20categories&sortBy=Relevance).

### Other editors

If you are interested in creating an cecli plugin for your favorite editor,
please let us know by opening a
[GitHub issue](https://github.com/dwash96/cecli/issues).


