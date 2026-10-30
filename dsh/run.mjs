/** Boot the minimal profile and submit one complete game to the native dsh AgentLoop. */
import { randomUUID } from 'node:crypto'
import { appendFileSync, copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { boot } from '@deepseek-ai/dsh-app-boot'
import { BlockAssembler, createUserMessage } from '@deepseek-ai/dsh-llm'
import { SessionId } from '@deepseek-ai/dsh-session'
import { Config as ContextConfig, resolveConfig as resolveContextConfig } from 'dsh-strata'

export const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const profilePath = fileURLToPath(new URL('./profile.yml', import.meta.url))
const configPath = fileURLToPath(new URL('./config.json', import.meta.url))

function positive(value, name, minimum = 1) {
  if (!Number.isSafeInteger(value) || value < minimum) throw new Error(`${name} must be an integer >= ${minimum}`)
  return value
}

/** Exposed for the scripted end-to-end test; setup may register a model adapter, never another loop. */
export async function runEpisode(input = {}, { setup, signal } = {}) {
  const settings = JSON.parse(readFileSync(input.runConfig ?? configPath, 'utf8'))
  const options = {
    projectRoot, seed: 0, output: resolve(projectRoot, 'results/dsh'), ...settings, ...input,
    model: { ...settings.model, ...input.model },
    context: resolveContextConfig(ContextConfig({ ...settings.context, ...input.context })),
  }
  const { mode } = options.context
  const { provider, id: model, maxOutputTokens, reasoningEffort } = options.model
  if (!Number.isSafeInteger(options.seed)) throw new Error('seed must be a safe integer')
  positive(maxOutputTokens, 'model.maxOutputTokens')
  if (!['off', 'low', 'high', 'max'].includes(reasoningEffort)) throw new Error('model.reasoningEffort must be off, low, high, or max')
  positive(options.maxRequests, 'maxRequests')
  // Persist the effective summary budget instead of an unresolved inheritance marker.
  options.context.summary.maxOutputTokens ??= maxOutputTokens
  if (options.config) options.config = resolve(options.config)
  const stamp = new Date().toISOString().replaceAll(':', '-')
  options.runDir = join(resolve(options.output), `${mode}-seed${options.seed}-${stamp}-${randomUUID().slice(0, 8)}`)
  mkdirSync(options.runDir, { recursive: true })
  const json = (file, value) => writeFileSync(join(options.runDir, file), JSON.stringify(value, null, 2) + '\n')
  json('run.json', { ...options, protocol: 'daily-orders-v2' })
  json('config.json', { model: options.model, context: options.context, maxRequests: options.maxRequests })
  copyFileSync(profilePath, join(options.runDir, 'profile.yml'))
  writeFileSync(join(options.runDir, 'api.jsonl'), '', { flag: 'wx' })
  const calls = []
  let ctx, agent, error, reason, stoppedAtGameEnd = false
  const cancel = () => agent?.cancel({ kind: 'user' })
  try {
    signal?.throwIfAborted()
    ctx = await boot('strata', profilePath, [], async host => {
      host.provide('strataOptions', options)
      if (setup) await setup(host)
      registerModelLog(host, options, calls)
    })
    // This profile has no optional enabled plugins. Cordis FiberState.ACTIVE is 2.
    const inactive = [...ctx.get('loader').entries()].filter(entry => !entry.disabled && entry.fiber?.state !== 2)
    if (inactive.length) throw new Error(`Profile plugins did not activate: ${inactive.map(entry => entry.id).join(', ')}`)
    if (!ctx.get('strataGame')) throw new Error('Strata adapter did not start; inspect the profile startup errors')
    // Own the episode boundary before any memory hooks: no sampling or compaction after Env.done.
    ctx.on('agent/pre-step', (_payload, next) => {
      if (!ctx.get('strataGame').current.done) return next()
      stoppedAtGameEnd = true
      return Promise.resolve({ kind: 'reject' })
    }, { prepend: true })
    agent = await ctx.get('agentLoop').create(SessionId(`strata-${randomUUID()}`), {
      provider, model, maxTokens: maxOutputTokens, reasoningEffort,
    }, { cwd: options.projectRoot })
    signal?.addEventListener('abort', cancel, { once: true })
    signal?.throwIfAborted()
    agent.followup(createUserMessage({ content: [{ type: 'text', text: '开始这一局。持续完成采购，直到整局结束。' }], source: { kind: 'user' } }))
    await agent.whenIdle()
    await ctx.get('sessions').flush(agent.session)
    reason = agent.session.snapshotEvents().findLast(event => event.type === 'turn/end')?.data.reason
    if (!(stoppedAtGameEnd && reason?.kind === 'blocked')) {
      error = reason?.kind === 'completed' ? 'Agent gave a final answer before the game ended'
        : reason?.error?.message ?? `Agent ended with ${reason?.kind ?? 'no terminal event'}`
    }
  } catch (failure) {
    error = failure instanceof Error ? failure.message : String(failure)
  } finally {
    signal?.removeEventListener('abort', cancel)
  }
  let result
  try {
    result = summarizeRun(options, { game: ctx?.get('strataGame'), agent, calls, error, reason, stoppedAtGameEnd })
  } finally {
    await ctx?.fiber.dispose()
  }
  json('summary.json', result)
  return result
}

/** Record task and summary requests through the same model stream hook. */
function registerModelLog(ctx, options, calls) {
  const apiPath = join(options.runDir, 'api.jsonl')
  const audit = value => appendFileSync(apiPath, JSON.stringify(value) + '\n')
  ctx.on('llm/stream', (request, next) => (async function* () {
    if (calls.length >= options.maxRequests) {
      audit({ type: 'request-limit', maxRequests: options.maxRequests })
      throw new Error(`Run request limit reached (${options.maxRequests})`)
    }
    const id = calls.length + 1
    const { signal: _signal, ...loggedRequest } = request
    const call = { id, purpose: request.purpose ?? 'task' }
    calls.push(call)
    audit({ type: 'request', id, request: loggedRequest })
    const assembler = new BlockAssembler()
    const chunks = []
    const started = Date.now()
    try {
      for await (const chunk of next()) { chunks.push(chunk); assembler.push(chunk); yield chunk }
    } catch (failure) {
      call.error = String(failure)
      throw failure
    } finally {
      call.usage = assembler.usage
      call.elapsedMs = Date.now() - started
      audit({ type: 'response', ...call, stream: chunks })
    }
  })(), { prepend: true })
}

/** Combine the final game state, model usage and native session events for summary.json. */
function summarizeRun(options, { game, agent, calls, error, reason, stoppedAtGameEnd }) {
  const current = game?.current
  const completed = !error && current?.done === true && stoppedAtGameEnd && reason?.kind === 'blocked'
  const lives = current?.lives ?? []
  const all = lives.flat()
  const early = lives.slice(1).flatMap(life => life.slice(0, 20))
  const mean = values => values.length ? values.filter(Boolean).length / values.length : null
  const usage = {}
  for (const call of calls) for (const [key, count] of Object.entries(call.usage ?? {})) {
    if (typeof count === 'number') usage[key] = (usage[key] ?? 0) + count
  }
  const events = agent?.session.snapshotEvents() ?? []
  return {
    eval_completed: completed, termination: completed ? 'env_done' : reason?.kind ?? 'startup_error',
    error: error ?? null, runDir: options.runDir,
    mode: options.context.mode, seed: options.seed, provider: options.model.provider, model: options.model.id,
    sessionId: agent?.session.id ?? null, daysPlayed: current?.days_played ?? 0,
    actions: game?.actions ?? 0, invalidActions: game?.invalidActions ?? 0,
    calls: calls.length, summaryCalls: calls.filter(call => call.purpose === 'compaction').length,
    windows: events.filter(event => event.type === 'user/message' && event.data.source.kind === 'context-window'
      && event.data.source.event === 'open').length,
    usage, callsWithoutUsage: calls.filter(call => call.usage === undefined).length,
    score: completed ? { overall: mean(all), perLife: lives.map(mean), rebirthEarly: mean(early), lives } : null,
  }
}

async function main() {
  const names = ['mode', 'seed', 'config', 'run-config', 'output', 'env-file']
  const { values } = parseArgs({ options: { ...Object.fromEntries(names.map(name => [name, { type: 'string' }])), help: { type: 'boolean' } } })
  if (values.help) {
    console.log('node dsh/run.mjs [--run-config dsh/config.json] [--mode notes] [--seed 0]\n'
      + '  [--config config/dsh-smoke.toml] [--output DIR] [--env-file FILE]\n'
      + 'Model and context controls live in dsh/config.json; --mode overrides context.mode.\n'
      + 'See docs/dsh.md for field meanings and experiment configuration.')
    return
  }
  if (values['env-file']) process.loadEnvFile(resolve(values['env-file']))
  const options = {}
  for (const key of ['config', 'output']) if (values[key] !== undefined) options[key] = values[key]
  if (values['run-config'] !== undefined) options.runConfig = resolve(values['run-config'])
  if (values.seed !== undefined) options.seed = Number(values.seed)
  if (values.mode !== undefined) options.context = { mode: values.mode }
  const controller = new AbortController()
  const abort = () => controller.abort(new Error('Run interrupted'))
  process.on('SIGINT', abort).on('SIGTERM', abort)
  try {
    const result = await runEpisode(options, { signal: controller.signal })
    console.log(JSON.stringify(result, null, 2))
    if (!result.eval_completed) process.exitCode = 1
  } finally { process.off('SIGINT', abort).off('SIGTERM', abort) }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error(error.message); process.exitCode = 1 })
}
