The worker no longer keeps a database transaction open while it calls GitHub, runs git clone / fetch / checkout, or publishes the result. The analysis pipeline itself still runs in one transaction.
