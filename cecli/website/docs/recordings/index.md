---
title: Screen recordings
has_children: true
nav_order: 75
has_toc: false
description: Screen recordings of cecli building cecli.
highlight_image: /assets/recordings.jpg
---

# Screen recordings

Below are a series of screen recordings of the cecli developer using cecli
to enhance cecli.
They contain commentary that describes how cecli is being used,
and might provide some inspiration for your own use of cecli.

{% assign sorted_pages = site.pages | where: "parent", "Screen recordings" | sort: "nav_order" %}
{% for page in sorted_pages %}
- [{{ page.title }}]({{ page.url | relative_url }}) - {{ page.description }}
{% endfor %}

