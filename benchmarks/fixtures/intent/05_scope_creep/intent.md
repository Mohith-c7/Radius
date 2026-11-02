# PR: add slugify

Add `slugify(title)` to `text_utils.py`.

- It lowercases the title and replaces each run of non-alphanumeric
  characters with a single `-`.
- Leading and trailing `-` are removed.
