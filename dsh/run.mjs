/** Boot the minimal profile and submit one complete game to the native dsh AgentLoop. */
import { randomUUID } from 'node:crypto'
import { appendFileSync, copyFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { boot } from '@deepseek-ai/dsh-app-boot'
import { BlockAssembler, createUserMessage } from '@deepseek-ai/dsh-llm'
import { SessionId } from '@deepseek-ai/dsh-session'

export const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const profilePath = fileURLToPath(new URL('./profile.yml', import.meta.url))

function positive(value, name, minimum = 1) {
  if (!Number.isSafeInteger(value) || value < minimum) throw new Error(`${name} must be an integer >= ${minimum}`)
  return value
}

/** Exposed for the scripted end-to-end test; setup may register a model adapter, never another loop. */
export async function runEpisode(input = {}, { setup, signal } = {}) {
  const options = {
    projectRoot, seed: 0, mode: 'notes', provider: 'deepseek-official', model: 'deepseek-flash',
    maxTokens: 8192, maxRequests: 10000, memory: {}, output: resolve(projectRoot, 'results/dsh'), ...input,
  }
  if (!['full', 'summary', 'notes'].includes(options.mode)) throw new Error('mode must be full, summary, or notes')
  if (!Number.isSafeInteger(options.seed)) throw new Error('seed must be a safe integer')
  positive(options.maxTokens, 'maxTokens')
  positive(options.maxRequests, 'maxRequests')
  if (options.config) options.config = resolve(options.config)
  const stamp = new Date().toISOString().replaceAll(':', '-')
  options.runDir = join(resolve(options.output), `${options.mode}-seed${options.seed}-${stamp}-${randomUUID().slice(0, 8)}`)
  mkdirSync(options.runDir, { recursive: true })
  const json = (file, value) => writeFileSync(join(options.runDir, file), JSON.stringify(value, null, 2) + '\n')
  json('run.json', { ...options, protocol: 'daily-orders-v2' })
  copyFileSync(profilePath, join(options.runDir, 'profile.yml'))
  const apiPath = join(options.runDir, 'api.jsonl')
  writeFileSync(apiPath, '', { flag: 'wx' })
  const audit = value => appendFileSync(apiPath, JSON.stringify(value) + '\n')
  const calls = []
  let ctx, agent, error, reason, stoppedAtGameEnd = false
  const cancel = () => agent?.cancel({ kind: 'user' })
  try {
    signal?.throwIfAborted()
    ctx = await boot('strata', profilePath, [], async host => {
      host.provide('strataOptions', options)
      if (setup) await setup(host)
      host.on('llm/stream', (request, next) => (async function* () {
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
      provider: options.provider, model: options.model, maxTokens: options.maxTokens,
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
    const game = ctx?.get('strataGame')
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
    result = {
      eval_completed: completed, termination: completed ? 'env_done' : reason?.kind ?? 'startup_error',
      error: error ?? null, runDir: options.runDir,
      mode: options.mode, seed: options.seed, provider: options.provider, model: options.model,
      sessionId: agent?.session.id ?? null, daysPlayed: current?.days_played ?? 0,
      actions: game?.actions ?? 0, invalidActions: game?.invalidActions ?? 0,
      calls: calls.length, summaryCalls: calls.filter(call => call.purpose === 'compaction').length,
      windows: events.filter(event => event.type === 'user/message' && event.data.source.kind === 'context-window'
        && event.data.source.event === 'open').length,
      usage, callsWithoutUsage: calls.filter(call => call.usage === undefined).length,
      score: completed ? { overall: mean(all), perLife: lives.map(mean), rebirthEarly: mean(early), lives } : null,
    }
  } finally {
    await ctx?.fiber.dispose()
  }
  json('summary.json', result)
  return result
}

async function main() {
  const names = ['mode', 'seed', 'config', 'model', 'output', 'env-file', 'context-tokens', 'summary-tokens',
    'max-tokens', 'max-requests', 'fallback-buffer', 'reminder-tokens']
  const { values } = parseArgs({ options: { ...Object.fromEntries(names.map(name => [name, { type: 'string' }])), help: { type: 'boolean' } } })
  if (values.help) {
    console.log('node dsh/run.mjs --mode notes --seed 0 [--config config/dsh-smoke.toml] [--output DIR] [--env-file FILE]\n'
      + 'Model: --model ID --max-tokens N --max-requests N\n'
      + 'Memory: --context-tokens N --summary-tokens N --fallback-buffer N --reminder-tokens N\n'
      + 'See docs/dsh.md for the minimal profile and full configuration.')
    return
  }
  if (values['env-file']) process.loadEnvFile(resolve(values['env-file']))
  const options = { memory: {} }
  for (const key of ['mode', 'model', 'config', 'output']) if (values[key] !== undefined) options[key] = values[key]
  for (const [flag, key] of [['seed', 'seed'], ['max-tokens', 'maxTokens'], ['max-requests', 'maxRequests']]) {
    if (values[flag] !== undefined) options[key] = Number(values[flag])
  }
  for (const [flag, key] of [['context-tokens', 'contextTokens'], ['fallback-buffer', 'fallbackBufferTokens'], ['reminder-tokens', 'reminderThresholdTokens']]) {
    if (values[flag] !== undefined) options.memory[key] = Number(values[flag])
  }
  if (values['summary-tokens'] !== undefined) options.memory.summary = { maxTokens: Number(values['summary-tokens']) }
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
