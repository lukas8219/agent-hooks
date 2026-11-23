# Static discovery hints

Work from the edges inward. Entry points tell you what the features are. Calls and requires tell you which files each feature touches. Specs tell you how to verify it.

## Entry points by stack

| Stack | Where features start |
|---|---|
| Rails | `config/routes.rb` (`bin/rails routes` if it boots), `app/controllers`, `app/views` + nav partials, `app/jobs`, `app/mailers`, `lib/tasks/*.rake` |
| Sinatra / Roda / Grape | `get`/`post`/`route` blocks in `app/**`, `config.ru` mounts, `routes/`, `controllers/` |
| Hanami | `config/routes.rb`, `app/actions` |
| Crystal (Kemal, Lucky, Amber, plain `HTTP::Server`) | `get "/..." do` blocks, `src/**/actions`, `HTTP::Handler` subclasses, `src/**/cli*.cr` |
| Go | `http.HandleFunc`, `mux.Handle`, chi, gin or echo route tables, `cmd/*/main.go`, cobra commands |
| Node / TS | express, fastify, koa or Next routers, `pages/`, `app/` dirs, `bin` scripts |
| Python | flask, fastapi or django `urls.py`, click or argparse CLIs |
| Frontend SPA | router config, top-level nav, page components |
| Workers | AMQP consumers (`subscribe`, `queue.bind`, `Sneakers`, `Hutch`, `amqp-client`, `bunny`), cron or `whenever`, sidekiq or que jobs |

## Interfaces (what connects repos)

- **HTTP exposed:** every route this repo serves to other services. Prioritize `/api`, internal endpoints and webhooks over HTML pages.
- **HTTP consumed:** HTTP client wrappers (`Net::HTTP`, `HTTP::Client`, `Faraday`, `Excon`, `httpx`, `fetch`, `axios`, `requests`). Follow the base URL env var (e.g. `ACCOUNT_CONSOLE_URL`) to name the target. Record both the `http:` key and the `env:` key.
- **AMQP:** `publish(` with an exchange and routing key, and queue or exchange declarations and bindings. A publisher `exposes`, and a subscriber `consumes`.
- **Database:** tables in migrations or `schema.rb`/`structure.sql`. Only record `db_table` interfaces for tables another repo also reads or writes, such as a shared database URL or the same table names in a sibling repo's queries.
- **Shared gems/packages:** internal gems in `Gemfile`, `shard.yml`, `go.mod` or `package.json`, especially git sources under the org.
- **Config/infra:** `docker-compose*.yml`, `.env.example`, `Procfile` and `README` show which sibling services must run. These are the source for `REQUIRES` edges marked `inferred`.

## Mapping files to a feature

1. Start at the entry file (role `entry`).
2. Follow the code it calls, such as models, service objects, clients and helpers, to `core` files. Stop at generic infrastructure (base classes, logging, DB connection) unless the feature is that infrastructure.
3. Add views, templates and assets that only this feature renders (role `view`).
4. Add migrations for the tables it owns (role `migration`), and config that toggles it (role `config`).
5. Add specs and tests that exercise it (role `test`), and make each runnable spec file a `test` check with an exact command.
6. Co-change pass: run `git log --since=12.months --name-only --format=%x00 -- <entry files>`. Files that often change together with the entry files are candidates. Read them before adding them, then add them with confidence 0.5 to 0.7.
7. A file may belong to several features. Shared utilities used by more than about 5 features should not be mapped. Mention them in the report instead.

## Granularity

- A feature is something a user or an operator would name: "Create instance", "Invoices", "Team invitations", "Metrics ingestion", "Alarm notifications".
- Aim for 10 to 60 features per repo, with 3 to 40 files each. Split anything larger.
- Slugs are stable, lowercase and hyphenated, so a refresh keeps the same ids.

## Test commands

Find how the repo runs tests: `bin/test`, a `Makefile` target, `Rakefile`, `.github/workflows/*.yml`, or `package.json` scripts. Use the same form, narrowed to files: `bundle exec rspec <files>`, `bin/rails test <files>`, `crystal spec <files>`, `go test ./pkg/...`, `npx jest <files>`. Check the command shape on one spec if the repo's deps are installed. Otherwise copy it from CI.
