---
parent: More info
nav_order: 500
description: Opt-in, anonymous, no personal info.
---

# Analytics

cecli can collect anonymous analytics to help
improve cecli's ability to work with LLMs, edit code and complete user requests.

## Opt-in, anonymous, no personal info

Analytics are only collected if you agree and opt-in. 
cecli respects your privacy and never collects your code, chat messages, keys or
personal info.

cecli collects information on:

- which LLMs are used and with how many tokens,
- which of cecli's edit formats are used,
- how often features and commands are used,
- information about exceptions and errors,
- etc

These analytics are associated with an anonymous,
randomly generated UUID4 user identifier.

This information helps improve cecli by identifying which models, edit formats,
features and commands are most used.
It also helps uncover bugs that users are experiencing, so that they can be fixed
in upcoming releases.

## Disabling analytics

You can opt out of analytics forever by running this command one time:

```
cecli --analytics-disable
```

## Enabling analytics

The `--[no-]analytics` switch controls whether analytics are enabled for the
current session:

- `--analytics` will turn on analytics for the current session.
This will *not* have any effect if you have permanently disabled analytics 
with `--analytics-disable`.
If this is the first time you have enabled analytics, cecli
will confirm you wish to opt-in to analytics.
- `--no-analytics` will turn off analytics for the current session.
- By default, if you don't provide `--analytics` or `--no-analytics`,
cecli will enable analytics for a random subset of users.
Such randomly selected users will be asked if they wish to opt-in to analytics.
This will never happen if you have permanently disabled analytics 
with `--analytics-disable`.

## Opting in

The first time analytics are enabled, you will need to agree to opt-in.

```
cecli --analytics

cecli respects your privacy and never collects your code, prompts, chats, keys or any personal
info.
For more info: https://cecli.dev/docs/more/analytics.html
Allow collection of anonymous analytics to help improve cecli? (Y)es/(N)o [Yes]:
```

If you say "no", analytics will be permanently disabled.


## Details about data being collected

### Sample analytics data

To get a better sense of what type of data is collected, you can review some
[sample analytics logs](https://github.com/dwash96/cecli/blob/main/cecli/website/assets/sample-analytics.jsonl).
These are the last 1,000 analytics events from the author's
personal use of cecli, updated regularly.


### Analytics code

Since cecli is open source, all the places where cecli collects analytics
are visible in the source code.
They can be viewed using 
[GitHub search](https://github.com/search?q=repo%3Acecli-ai%2Fcecli+%22.event%28%22&type=code).


### Logging and inspecting analytics

You can get a full log of the analytics that cecli is collecting,
in case you would like to audit or inspect this data.

```
cecli --analytics-log filename.jsonl
```

If you want to just log analytics without reporting them, you can do:

```
cecli --analytics-log filename.jsonl --no-analytics
```

### Sending analytics to custom PostHog project or installation

cecli uses PostHog for analytics collection. You can configure cecli to send analytics to your own PostHog project or a custom PostHog installation using these parameters:

- `--analytics-posthog-project-api-key KEY` - Set a custom PostHog project API key
- `--analytics-posthog-host HOST` - Set a custom PostHog host (default is app.posthog.com)

## Reporting issues

If you have concerns about any of the analytics that cecli is collecting
or our data practices
please contact us by opening a
[GitHub Issue](https://github.com/dwash96/cecli/issues).

## Privacy policy

Please see cecli's
[privacy policy](/docs/legal/privacy.html)
for more details.

