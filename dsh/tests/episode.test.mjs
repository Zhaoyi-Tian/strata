import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { load as loadYaml, dump as dumpYaml } from 'js-yaml'
import { LlmAdapter, ToolCallId } from '@deepseek-ai/dsh-llm'
import { projectRoot, runEpisode } from '../run.mjs'

const root = resolve(process.env.STRATA_TEST_ROOT ?? join(projectRoot, 'dsh/node_modules/.cache/tests'))
mkdirSync(root, { recursive: true })
const textOf = request => request.messages.flatMap(m => m.content).filter(b => b.type === 'text').map(b => b.text).join('\n')
const rows = path => readFileSync(path, 'utf8').trim().split('\n').map(JSON.parse)

class Scripted extends LlmAdapter {
  step = 0
  normal = 0
  constructor(ctx, mode, behavior) { super(); this.ctx = ctx; this.mode = mode; this.behavior = behavior }
  async resolveModel(provider, model) {
    return { provider, id: model, name: model, context: { contextWindow: 1000000 },
      reasoning: { efforts: [{ id: 'low', name: 'Low' }] } }
  }
  async *stream(request) {
    let block
    const game = this.ctx.get('strataGame')
    assert.equal(game.current.done, false, 'runner stops before any model call after game completion')
    assert.ok(!JSON.stringify(request).includes('source_layer'), 'evaluation truth never enters requests')
    assert.ok(!JSON.stringify(request).includes('daily-orders-v2'), 'evaluation metadata stays out of prompts')
    assert.equal(request.maxTokens, 1536, 'normal calls and summaries share the configured output budget')
    assert.equal(request.reasoningEffort, 'low', 'all modes and summaries share the configured reasoning effort')
    const names = request.tools.map(t => t.name)
    if (request.purpose === 'compaction') {
      assert.equal(this.mode, 'summary')
      block = { type: 'text', text: 'Continue the current procurement game. Past observations may be outdated.' }
    } else {
      this.normal++
      assert.equal(names.length, this.mode === 'notes' ? 11 : 1)
      assert.ok(names.includes('strata_step'))
      if (!game.current.done) assert.ok(textOf(request).includes(game.current.observation), 'current screen survives memory operations')
      if (this.behavior === 'early' || game.current.done) block = { type: 'text', text: 'done' }
      else if (this.behavior === 'error') {
        yield { type: 'finish', reason: { kind: 'error', failure: { code: 'UPSTREAM', message: 'scripted API failure' } } }
        return
      } else {
        let name = 'strata_step', args = { action: '不做' }
        if (this.mode === 'notes') {
          if (this.step === 0) { name = 'notes_write_file'; args = { path: 'checkpoint.md', text: 'CHECKPOINT: continue procurement.' } }
          if (this.step === 1) { name = 'new_context'; args = {} }
          if (this.step === 2) {
            assert.ok(!textOf(request).includes('开始这一局'), 'old instruction was cleared')
            name = 'notes_read_file'; args = { path: 'checkpoint.md' }
          }
          if (this.step === 3) {
            assert.ok(textOf(request).includes('CHECKPOINT'))
            name = 'history_list_items'; args = { window_id: 'w0', event_type: 'user/message' }
          }
          if (this.step === 4) {
            assert.ok(textOf(request).includes('开始这一局'), 'history recovers the original user request')
            args = { action: '去 火星' }
          }
        }
        block = { type: 'tool-call', id: ToolCallId(`script-${this.step++}`), name, arguments: JSON.stringify(args) }
      }
    }
    const reasoning = { type: 'reasoning', text: 'Scripted reasoning retained in the native session.' }
    for (const [index, item] of [reasoning, block].entries()) {
      yield { type: 'block-start', index, blockType: item.type }
      if (item.type === 'tool-call') yield { type: 'tool-call-delta', index, id: item.id, name: item.name, argumentsDelta: item.arguments }
      else yield { type: item.type === 'reasoning' ? 'reasoning-delta' : 'text-delta', index, text: item.text }
      yield { type: 'block-end', index, block: item }
    }
    yield { type: 'usage', usage: { inputTokens: this.mode === 'summary' && !request.purpose ? 7000 : 1000, cacheReadTokens: 100, outputTokens: 20 } }
    yield { type: 'finish', reason: { kind: block.type === 'tool-call' ? 'tool-calls' : 'stop' } }
  }
}

async function trial(mode, behavior, check, extra = {}) {
  const output = mkdtempSync(join(root, 'episode-'))
  try {
    const result = await runEpisode({
      model: { provider: 'scripted', maxOutputTokens: 1536, reasoningEffort: 'low' },
      output, config: join(projectRoot, 'config/dsh-smoke.toml'),
      context: { mode, summary: { compactAtTokens: 6144 } }, ...extra,
    }, { setup(ctx) {
      ctx.inject(['llm'], child => child.llm.registerAdapter(['scripted'], new Scripted(child, mode, behavior)))
    } })
    await check(result)
  } finally { rmSync(output, { recursive: true, force: true }) }
}

for (const mode of ['full', 'summary', 'notes']) {
  test(`${mode}: real profile, persistent Env, native tools and durable reasoning`, async () => {
    await trial(mode, undefined, result => {
      assert.equal(result.eval_completed, true, result.error)
      assert.equal(result.daysPlayed, 8)
      assert.equal(result.termination, 'env_done')
      if (mode === 'full') assert.equal(result.calls, 8, 'no extra final-answer request')
      assert.deepEqual(result.score.lives.map(l => l.length), [4, 4])
      assert.equal(result.score.overall, 0) // scripted model always skips
      assert.equal(result.invalidActions, mode === 'notes' ? 1 : 0)
      assert.ok(result.usage.cacheReadTokens > 0)
      assert.equal(result.summaryCalls > 0, mode === 'summary')
      assert.equal(result.windows > 1, mode === 'notes')
      const env = rows(join(result.runDir, 'env.jsonl'))
      const settings = JSON.parse(readFileSync(join(result.runDir, 'config.json'), 'utf8'))
      assert.equal(settings.model.maxOutputTokens, 1536)
      assert.equal(settings.context.summary.maxOutputTokens, 1536)
      assert.equal(settings.context.mode, mode)
      assert.equal(env.filter(e => e.kind === 'start').length, 1, 'context switches never reset the Env')
      assert.equal(env.filter(e => e.kind === 'continue').length, 1)
      assert.ok(env.every(e => e.truth))
      const api = rows(join(result.runDir, 'api.jsonl'))
      assert.ok(api.some(e => e.type === 'response' && e.stream.some(c => c.type === 'reasoning-delta')))
      assert.ok(!JSON.stringify(api.filter(e => e.type === 'request')).includes('source_layer'))
    })
  })
}

test('an early final answer is incomplete, with no ordinary zero score', async () => {
  await trial('full', 'early', result => {
    assert.equal(result.eval_completed, false)
    assert.equal(result.score, null)
    assert.match(result.error, /before the game ended/)
  })
})

test('API failure is incomplete and retains the failure response', async () => {
  await trial('full', 'error', result => {
    assert.equal(result.eval_completed, false)
    assert.equal(result.score, null)
    assert.match(result.error, /scripted API failure/)
    assert.ok(rows(join(result.runDir, 'api.jsonl')).some(e => e.type === 'response'
      && e.stream.some(c => c.type === 'finish' && c.reason.kind === 'error')))
  })
})

test('request limits terminate the run as incomplete', async () => {
  await trial('full', undefined, result => {
    assert.equal(result.eval_completed, false)
    assert.equal(result.score, null)
    assert.equal(result.calls, 2)
    assert.match(result.error, /request limit/)
  }, { maxRequests: 2 })
})

test('full context limit ends an experiment as incomplete and keeps the original session', async () => {
  const dir = mkdtempSync(join(root, 'config-'))
  const runConfig = join(dir, 'experiment.yml')
  const settings = loadYaml(readFileSync(join(projectRoot, 'dsh/config.yml'), 'utf8'))
  settings.model.id = 'controlled-model'
  settings.context.full.stopAtTokens = 1000
  writeFileSync(runConfig, '# 本轮实验的独立配置\n' + dumpYaml(settings))
  try {
    await trial('full', undefined, result => {
      assert.equal(result.eval_completed, false)
      assert.equal(result.score, null)
      assert.match(result.error, /full: context reached stopAtTokens/)
      assert.equal(result.model, 'controlled-model')
      assert.equal(result.calls, 1)
      assert.equal(result.summaryCalls, 0)
      assert.equal(result.windows, 0)
      const effective = JSON.parse(readFileSync(join(result.runDir, 'config.json'), 'utf8'))
      assert.equal(effective.context.full.stopAtTokens, 1000)
    }, { runConfig })
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
