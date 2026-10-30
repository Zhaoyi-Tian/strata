/** One native game tool backed by one persistent Python Env. */
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import { join } from 'node:path'
import { defineTool } from '@deepseek-ai/dsh-tools'

class GameProcess {
  constructor(options) {
    const args = ['run', '--no-sync', '--project', options.projectRoot, 'python', '-u', '-m', 'stratabench.dsh_env',
      '--seed', String(options.seed), '--log', join(options.runDir, 'env.jsonl')]
    if (options.config) args.push('--config', options.config)
    this.child = spawn('uv', args, {
      cwd: options.projectRoot, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    })
    this.ready = Promise.withResolvers()
    this.pending = this.ready
    this.stderr = ''
    this.exited = new Promise(resolve => this.child.once('close', resolve))
    this.child.stderr.on('data', chunk => { this.stderr = (this.stderr + chunk).slice(-16000) })
    this.child.on('error', error => this.fail(error))
    this.child.stdin.on('error', error => this.fail(error))
    this.child.on('close', code => this.fail(new Error(`Strata process exited (${code}): ${this.stderr}`)))
    this.lines = createInterface({ input: this.child.stdout })
    this.lines.on('line', line => {
      try {
        const packet = JSON.parse(line)
        if (!this.pending) throw new Error('Unexpected Strata response')
        if (packet.error) { this.fail(new Error(packet.error)); return }
        const pending = this.pending
        this.pending = undefined
        this.current = packet
        pending.resolve(packet)
      } catch (error) { this.fail(error) }
    })
  }

  fail(error) {
    this.failure ??= error
    this.pending?.reject(error)
    this.pending = undefined
  }

  async step(action, signal) {
    signal.throwIfAborted()
    if (this.failure) throw this.failure
    if (this.pending) throw new Error('Strata actions must run serially')
    const pending = Promise.withResolvers()
    this.pending = pending
    const abort = () => this.fail(signal.reason)
    signal.addEventListener('abort', abort, { once: true })
    try {
      this.child.stdin.write(JSON.stringify({ action }) + '\n')
      return await pending.promise
    } finally { signal.removeEventListener('abort', abort) }
  }

  async close() {
    this.child.stdin.end()
    const timer = setTimeout(() => this.child.kill('SIGTERM'), 2000)
    try { await this.exited } finally { clearTimeout(timer); this.lines.close() }
  }
}

export const name = 'strata-game'
export const inject = ['tools', 'systemPrompt']

export async function apply(ctx, options) {
  const game = new GameProcess(options)
  ctx.effect(() => () => game.close())
  const initial = await game.ready.promise
  ctx.provide('strataGame', game)
  ctx.systemPrompt.section({
    name: 'strata-rules', order: 0, complete: true, interpolate: false,
    text: `你在玩一个持续到整局结束的采办游戏。目标是最大化每天成单率。\n`
      + `下面动作说明里的“每一步只回一个动作”约束 strata_step 的 action 字段。实际请调用 strata_step 工具，`
      + `不要用普通文字代替动作。\n`
      + `请持续操作到 strata_step 返回“整局结束”，再给最终答复。死亡与重生由环境自动推进。\n\n`
      + initial.instructions,
  })
  ctx.systemPrompt.context({
    name: 'strata-current', order: 0, required: true, interpolate: false,
    text: () => game.current.observation,
  })
  ctx.tools.register(defineTool({
    name: 'strata_step',
    description: '执行一个游戏动作，返回结果和下一问。整局结束后停止调用。',
    parameters: { action: { type: 'string', required: true, description: '找 <人名> / 不做 / 去 <村名> / 留下' } },
    output: { schema: { type: 'string' }, render: (_args, text) => [{ type: 'text', text }] },
    async execute({ action }, exec) {
      if (game.current.done) return '整局结束。'
      const packet = await game.step(action, exec.signal)
      game.actions = (game.actions ?? 0) + 1
      game.invalidActions = (game.invalidActions ?? 0) + Number(!packet.parse_ok)
      return packet.feedback + (packet.done ? '\n整局结束。' : '')
    },
  }))
}
