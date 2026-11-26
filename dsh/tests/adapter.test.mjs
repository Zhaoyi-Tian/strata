import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { GameProcess, RequestError } from '../adapter.mjs'
import { projectRoot } from '../run.mjs'

const root = resolve(process.env.STRATA_TEST_ROOT ?? join(projectRoot, 'dsh/node_modules/.cache/tests'))
mkdirSync(root, { recursive: true })

async function withGame(check) {
  const runDir = mkdtempSync(join(root, 'adapter-'))
  const game = new GameProcess({ projectRoot, seed: 0, runDir, config: join(projectRoot, 'config/dsh-smoke.toml') })
  try {
    await game.ready.promise
    await check(game)
  } finally { await game.close(); rmSync(runDir, { recursive: true, force: true }) }
}

test('an aborted step still lands, and the game keeps working', () => withGame(async game => {
  const controller = new AbortController()
  const step = game.step('不做', controller.signal)
  await new Promise(resolve => setImmediate(resolve))   // the action is on its way to Python
  controller.abort(new Error('cancelled'))
  await assert.rejects(step, /cancelled/)
  const next = await game.step('不做', new AbortController().signal)
  assert.equal(next.days_played, 2, 'the abandoned action was applied, then this one')
  assert.equal(game.current, next)
}))

test('a rejected request is not fatal', () => withGame(async game => {
  await assert.rejects(game.step(123, new AbortController().signal), RequestError)
  const next = await game.step('不做', new AbortController().signal)
  assert.equal(next.days_played, 1)
}))
