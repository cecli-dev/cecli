---
title: Speed benchmarks of GPT-4 Turbo and gpt-3.5-turbo-1106
excerpt: This report provides a detailed comparison of the speed of GPT-4 Turbo and gpt-3.5-turbo-1106 models based on the cecli benchmarking suite.
canonical_url: https://cecli.dev/2023/11/06/benchmarks-speed-1106.html
highlight_image: /assets/benchmarks-speed-1106.jpg
nav_exclude: true
---
{% if page.date %}
<p class="post-date">{{ page.date | date: "%B %d, %Y" }}</p>
{% endif %}

# Speed benchmarks of GPT-4 Turbo and gpt-3.5-turbo-1106

<p class="post-date">{{ page.date | date: "%b %-d, %Y" }}</p>

[![benchmark results](/assets/benchmarks-speed-1106.svg)](https://cecli.dev/assets/benchmarks-speed-1106.svg)

[OpenAI just released new versions of GPT-3.5 and GPT-4](https://openai.com/blog/new-models-and-developer-products-announced-at-devday),
and there's a lot
of interest about their capabilities and performance.
With that in mind, I've been benchmarking the new models.

[cecli](https://github.com/dwash96/cecli)
is an open source command line chat tool that lets you work with GPT to edit
code in your local git repo.
cecli relies on a
[code editing benchmark](https://cecli.dev/docs/benchmarks.html)
to quantitatively evaluate
performance.

This is the latest in a series of reports
that use the cecli benchmarking suite to assess and compare the code
editing capabilities of OpenAI's GPT models. You can review previous
reports to get more background on cecli's benchmark suite:

- [GPT code editing benchmarks](https://cecli.dev/docs/benchmarks.html) evaluates the March and June versions of GPT-3.5 and GPT-4.
- [Code editing skill benchmarks for OpenAI's "1106" models](https://cecli.dev/docs/benchmarks-1106.html) compares the olders models to the November (1106) models.

## Speed

This report compares the **speed** of the various GPT models.
cecli's benchmark measures the response time of the OpenAI chat completion
endpoint each time it asks GPT to solve a programming exercise in the benchmark
suite. These results measure only the time spent waiting for OpenAI to
respond to the prompt.
So they are measuring
how fast these models can
generate responses which primarily consist of source code.

Some observations:

- **GPT-3.5 got 6-11x faster.** The `gpt-3.5-turbo-1106` model is 6-11x faster than the June (0613) version which has been the default `gpt-3.5-turbo` model.
- **GPT-4 Turbo is 2-2.5x faster.** The new `gpt-4-1106-preview` model is 2-2.5x faster than the June (0613) version which has been the default `gpt-4` model.
- The old March (0301) version of GPT-3.5 is actually faster than the June (0613) version. This was a surprising discovery.

## Updates

Last updated 11/14/23.
OpenAI has relaxed rate limits so these results are no longer considered preliminary.
