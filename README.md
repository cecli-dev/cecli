## Why `aider-ce`?

`aider-ce` (aka `cecli`, probably pronounced like "Cecily") is a community-driven fork of the [Aider](https://aider.chat/) AI pair programming tool.
Aider is a fantastic piece of software with a wonderful community but it has been painfully slow in receiving updates in the quickly evolving AI tooling space.

We aim to foster an open, collaborative ecosystem where new features, experiments, and improvements can be developed and shared rapidly. We believe in genuine FOSS principles and actively welcome contributors of all skill levels.

If you are looking for bleeding-edge features or want to get your hands dirty with the internals of an AI coding agent, here's your sign.
LLMs are a part of our lives from here on out so join us in learning about and crafting the future.

### Links

[Discord Chat](https://discord.gg/AX9ZEA7nJn) 🞄
[Changelog](https://github.com/dwash96/aider-ce/blob/main/CHANGELOG.md) 🞄
[Issue Queue](https://github.com/dwash96/aider-ce/issues)

## Documentation/Other Notes:

* [Agent Mode](https://github.com/dwash96/aider-ce/blob/main/aider/website/docs/config/agent-mode.md)
* [MCP Configuration](https://github.com/dwash96/aider-ce/blob/main/aider/website/docs/config/mcp.md)
* [TUI Configuration](https://github.com/dwash96/aider-ce/blob/main/aider/website/docs/config/tui.md)
* [Skills](https://github.com/dwash96/aider-ce/blob/main/aider/website/docs/config/skills.md)
* [Session Management](https://github.com/dwash96/aider-ce/blob/main/aider/website/docs/sessions.md)
* [Advanced Model Configuration](https://github.com/dwash96/aider-ce/blob/main/aider/website/docs/config/model-aliases.md#advanced-model-settings)
* [Aider Original Documentation (still mostly applies)](https://aider.chat/)

You can see a selection of the enhancements and updates by comparing the help output:

```bash
diff -uw --color <(aider --help) <(cecli --help)
```

## Installation Instructions
This project can be installed using several methods:

### Package Installation
```bash
pip install aider-ce
```

or

```bash
uv pip install --native-tls aider-ce
```

The package exports an `aider-ce` command that accepts all of Aider's configuration options

### Tool Installation
```bash
uv tool install --native-tls --python python3.12 aider-ce
```

Use the tool installation so aider doesn't interfere with your development environment

## Configuration

The documentation above contains the full set of allowed configuration options
but I highly recommend using an `.aider.conf.yml` file. A good place to get started is:

```yaml
model: <model of your choice>
agent: true
auto-commits: true
auto-save: true
auto-load: false
cache-prompts: true
check-update: true
debug: false
enable-context-compaction: true
context-compaction-max-tokens: 64000
env-file: .aider.env
show-model-warnings: true
use-enhanced-map: true
watch-files: false
tui: true

agent-config:
  large_file_token_threshold: 12500
  skip_cli_confirmations: false

mcp-servers:
  mcpServers:
    context7:
      transport: http
      url: https://mcp.context7.com/mcp
```

Use the adjacent .aider.env file to store model api keys as environment variables, e.g:

```
ANTHROPIC_API_KEY="..."
GEMINI_API_KEY="..."
OPENAI_API_KEY="..."
OPENROUTER_API_KEY="..."
DEEPSEEK_API_KEY="..."
```

### Run Program

If you are in the directory with your .aider.conf.yml file, then simply running `aider-ce` or `cecli` will start the agent with your configuration. If you want additional sandboxing, we publish a docker container that can be ran as follows:

```bash
docker pull dustinwashington/aider-ce
docker run \
  -it \
  --user $(id -u):$(id -g) \
  --volume $(pwd):/app dustinwashington/aider-ce \
  --volume $(pwd)/.aider.conf.yml:/.aider.conf.yml \
  --volume $(pwd)/.aider.env:/.aider/.env \
  --config /app/.aider.conf.yml
```

This command will make sure all commands ran by the coding agent happen in context of the docker container to protect the host file system from any infamous agentic mishap

## Project Roadmap/Goals

The current priorities are to improve core capabilities and user experience of the Aider project

1. **Base Asynchronicity (aider-ce coroutine-experiment branch)**
  * [x] Refactor codebase to have the main loop run asynchronously
  * [x] Update test harness to work with new asynchronous methods

2. **Repo Map Accuracy** - [Discussion](https://github.com/dwash96/aider-ce/issues/45)
  * [x] [Bias page ranking toward active/editable files in repo map parsing](https://github.com/Aider-AI/aider/issues/2405)
  * [x] [Include import information in repo map for richer context](https://github.com/Aider-AI/aider/issues/2688)
  * [x] [Handle non-unique symbols that break down in large codebases](https://github.com/Aider-AI/aider/issues/2341)

3. **Context Discovery** - [Discussion](https://github.com/dwash96/aider-ce/issues/46)
  * [ ] Develop AST-based search capabilities
  * [ ] Enhance file search with ripgrep integration
  * [ ] Implement RAG (Retrieval-Augmented Generation) for better code retrieval
  * [ ] Build an explicit workflow and local tooling for internal discovery mechanisms

4. **Context Delivery** - [Discussion](https://github.com/dwash96/aider-ce/issues/47)
  * [ ] Use workflow for internal discovery to better target file snippets needed for specific tasks
  * [ ] Add support for partial files and code snippets in model completion messages

5. **TUI Experience** - [Discussion](https://github.com/dwash96/aider-ce/issues/48)
  * [x] Add a full TUI (probably using textual) to have a visual interface competitive with the other coding agent terminal programs
  * [x] Re-integrate pretty output formatting
  * [x] Implement a response area, a prompt area with current auto completion capabilities, and a helper area for managing utility commands

6. **Agent Mode** - [Discussion](https://github.com/dwash96/aider-ce/issues/111)
  * [x] Renaming "navigator mode" to "agent mode" for simplicity
  * [x] Add an explicit "finished" internal tool
  * [x] Add a configuration json setting for agent mode to specify allowed local tools to use, tool call limits, etc.
  * [ ] Add a RAG tool for the model to ask questions about the codebase
  * [ ] Make the system prompts more aggressive about removing unneeded files/content from the context
  * [ ] Add a plugin-like system for allowing agent mode to use user-defined tools in simple python files
  * [x] Add a dynamic tool discovery tool to allow the system to have only the tools it needs in context

### All Contributors (Both Aider Main and Aider-CE)

<table>
<tbody>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=paul-gauthier">@paul-gauthier</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=dwash96">@dwash96</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=tekacs">@tekacs</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=ErichBSchulz">@ErichBSchulz</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=ei-grad">@ei-grad</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=joshuavial">@joshuavial</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=chrisnestrud">@chrisnestrud</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=chr15m">@chr15m</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=johbo">@johbo</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=fry69">@fry69</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=quinlanjager">@quinlanjager</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=caseymcc">@caseymcc</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=shladnik">@shladnik</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jamwil">@jamwil</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=itlackey">@itlackey</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=tomjuggler">@tomjuggler</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=szmania">@szmania</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=vk4s">@vk4s</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=titusz">@titusz</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=bphd">@bphd</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=daniel-vainsencher">@daniel-vainsencher</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=1broseidon">@1broseidon</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=akaihola">@akaihola</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jalammar">@jalammar</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=schpet">@schpet</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=iamFIREcracker">@iamFIREcracker</a></td>
<td>JV</td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=KennyDizi">@KennyDizi</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=ivanfioravanti">@ivanfioravanti</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=mdeweerd">@mdeweerd</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=itsmeknt">@itsmeknt</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=fahmad91">@fahmad91</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=cheahjs">@cheahjs</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=youknow04">@youknow04</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=pjcreath">@pjcreath</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=pcamp">@pcamp</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=miradnanali">@miradnanali</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=o-nix">@o-nix</a></td>
<td>Jonathan Ellis</td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=codeofdusk">@codeofdusk</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=claui">@claui</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jpshackelford">@jpshackelford</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=Taik">@Taik</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=Hambaobao">@Hambaobao</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=therealmarv">@therealmarv</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=muravvv">@muravvv</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=hypn4">@hypn4</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=gmoz22">@gmoz22</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=contributor">@contributor</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=ctoth">@ctoth</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=thehunmonkgroup">@thehunmonkgroup</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=gcp">@gcp</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=sentienthouseplant">@sentienthouseplant</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=ktakayama">@ktakayama</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=lreeves">@lreeves</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=nims11">@nims11</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=preynal">@preynal</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=tgbender">@tgbender</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=apaz-cli">@apaz-cli</a></td>
<td>Alexander Kjeldaas</td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=zhyu">@zhyu</a></td>
<td>Yutaka Matsubara</td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=burnettk">@burnettk</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=cryptekbits">@cryptekbits</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=deansher">@deansher</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=kennyfrc">@kennyfrc</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=lentil32">@lentil32</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=malkoG">@malkoG</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=mubashir1osmani">@mubashir1osmani</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=TimPut">@TimPut</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=zjy1412">@zjy1412</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=savioursho">@savioursho</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jayeshthk">@jayeshthk</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=susliko">@susliko</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=FeepingCreature">@FeepingCreature</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=misteral">@misteral</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=aelaguiz">@aelaguiz</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=DhirajBhakta">@DhirajBhakta</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=gopar">@gopar</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=eltociear">@eltociear</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=tao12345666333">@tao12345666333</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jpshack-at-palomar">@jpshack-at-palomar</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=smh">@smh</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=nhs000">@nhs000</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=sannysanoff">@sannysanoff</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=ryanfreckleton">@ryanfreckleton</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=mbokinala">@mbokinala</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=yamitzky">@yamitzky</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=mobyvb">@mobyvb</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=ozapinq">@ozapinq</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=nicolasperez19">@nicolasperez19</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=varchasgopalaswamy">@varchasgopalaswamy</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=ffluk3">@ffluk3</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=tanavamsikrishna">@tanavamsikrishna</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=tylersatre">@tylersatre</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=pcgeek86">@pcgeek86</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=tamirzb">@tamirzb</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=taha-yassine">@taha-yassine</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=strayer">@strayer</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=StevenTCramer">@StevenTCramer</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=Skountz">@Skountz</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=sestrella">@sestrella</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=rnevius">@rnevius</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=holoskii">@holoskii</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=Netzvamp">@Netzvamp</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=peterhadlaw">@peterhadlaw</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=pauldw">@pauldw</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=paulmaunders">@paulmaunders</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=omri123">@omri123</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=MatthewZMD">@MatthewZMD</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=mbailey">@mbailey</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=golergka">@golergka</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=matfat55">@matfat55</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=mtofano">@mtofano</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=maledorak">@maledorak</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=mlang">@mlang</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=marcomayer">@marcomayer</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=you-n-g">@you-n-g</a></td>
<td>wangboxue</td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=rti">@rti</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=prmbiy">@prmbiy</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=omarcinkonis">@omarcinkonis</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=Oct4Pie">@Oct4Pie</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=mark-asymbl">@mark-asymbl</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=yazgoo">@yazgoo</a></td>
<td>michal.sliwa</td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=mdklab">@mdklab</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=mario7421">@mario7421</a></td>
</tr>
<tr>
<td>liam.liu</td>
<td>kwmiebach</td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=kAIto47802">@kAIto47802</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jvmncs">@jvmncs</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=hydai">@hydai</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=hstoklosa">@hstoklosa</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=gordonlukch">@gordonlukch</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=develmusa">@develmusa</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=coredevorg">@coredevorg</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=cantalupo555">@cantalupo555</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=caetanominuzzo">@caetanominuzzo</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=yzx9">@yzx9</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=zackees">@zackees</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=wietsevenema">@wietsevenema</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=krewenki">@krewenki</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=vinnymac">@vinnymac</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=szepeviktor">@szepeviktor</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=lattwood">@lattwood</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=spdustin">@spdustin</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=henderkes">@henderkes</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=daysm">@daysm</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=devriesd">@devriesd</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=daniel-sc">@daniel-sc</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=damms005">@damms005</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=curran">@curran</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=cclauss">@cclauss</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=cjoach">@cjoach</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=csala">@csala</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=bexelbie">@bexelbie</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=branchv">@branchv</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=bkowalik">@bkowalik</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=h0x91b">@h0x91b</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=aroffe99">@aroffe99</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=banjo">@banjo</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=anjor">@anjor</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=andreypopp">@andreypopp</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=ivnvxd">@ivnvxd</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=andreakeesys">@andreakeesys</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=ameramayreh">@ameramayreh</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=a1ooha">@a1ooha</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=maliayas">@maliayas</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=akirak">@akirak</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=adrianlzt">@adrianlzt</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=codefromthecrypt">@codefromthecrypt</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=aweis89">@aweis89</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=aj47">@aj47</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=noitcudni">@noitcudni</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=solatis">@solatis</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=webkonstantin">@webkonstantin</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=khulnasoft-bot">@khulnasoft-bot</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=KebobZ">@KebobZ</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=acro5piano">@acro5piano</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=josx">@josx</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=joshvera">@joshvera</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jklina">@jklina</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jkeys089">@jkeys089</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=johanvts">@johanvts</a></td>
<td>Jim White</td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=gengjiawen">@gengjiawen</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jevon">@jevon</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jesstelford">@jesstelford</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=JeongJuhyeon">@JeongJuhyeon</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=jackhallam">@jackhallam</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=Mushoz">@Mushoz</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=zestysoft">@zestysoft</a></td>
<td>Henry Fraser</td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=gwpl">@gwpl</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=garrett-hopper">@garrett-hopper</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=filiptrplan">@filiptrplan</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=FelixLisczyk">@FelixLisczyk</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=evnoj">@evnoj</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=erykwieliczko">@erykwieliczko</a></td>
</tr>
<tr>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=elohmeier">@elohmeier</a></td>
<td><a href="https://github.com/dwash96/aider-ce/commits/main?author=emmanuel-ferdman">@emmanuel-ferdman</a></td>
<td></td>
<td></td>
</tr>
</tbody>
</table>