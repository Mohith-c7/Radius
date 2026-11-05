`POST /coverage` and the coverage `GET` routes no longer fail with a 500 when serializing their response, and `POST /coverage` returns 4xx for malformed `X-Analysis-Id`.
