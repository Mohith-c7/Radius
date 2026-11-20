The upload-results action now retries a 5xx or unreachable API 6 times over about 2.6 minutes (waits 5 to 80 s), so an upload that lands during a restart of a small API host is no longer lost.
