The dependency audit workflow no longer fails after the `actions/setup-node` 7 upgrade: its pnpm audit job installs nothing, so it no longer asks setup-node to cache a pnpm store.
