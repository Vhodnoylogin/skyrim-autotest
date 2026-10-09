// Development-only host mocks; never messages a real chat or invokes Python.
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../integrations/codex-voice-bridge.js', import.meta.url), 'utf8');
const run = new Function('tools', 'notify', 'text', 'setTimeout', 'VOICE_BRIDGE_CONFIG',
  'return (async()=>{\n' + source + '\n})()');
const config = {threadId: '01a108ca-6bff-7973-879e-81047149e1ef',
  inbox: 'C:/external/inbox', repository: 'C:/repo', durationSeconds: 1};

async function trial(mode) {
  const log = [], notices = [], pending = new Set();
  let sent = 0, next = 1;
  const result = value => ({exit_code: 0, output: JSON.stringify(value)});
  const tools = {
    exec_command: async ({cmd}) => {
      log.push(cmd);
      if (cmd.includes(' admit ')) {
        if (next <= 2) {
          const id = String(next++).repeat(32);
          return result({status: 'received', id, recordsSha256: 'a'.repeat(64),
            firstSeq: next - 1, lastSeq: next - 1});
        }
        return result({status: 'blocked', error: 'test end'});
      }
      if (cmd.includes('--receipt-ref')) return result({status: 'delivered'});
      if (cmd.includes(' dispatch ')) {
        const id = /--id '([^']+)'/.exec(cmd)[1];
        assert(!pending.has(id), 'must not reserve a dispatch twice');
        pending.add(id);
        return result({status: 'dispatching'});
      }
      throw Error('Unknown mock command');
    },
    mcp__codex_app__send_message_to_thread: async request => {
      sent++;
      assert.equal(request.threadId, config.threadId);
      assert(request.prompt.includes('deliveries entry'));
      assert(request.prompt.includes('first text reply'));
      if (mode === 'throw') throw Error('host disconnected');
      return {isError: mode === 'rejected', content: []};
    },
    apply_patch: async () => ({isError: mode === 'writefail'})
  };
  await run(tools, value => notices.push(value), () => {}, setTimeout, config);
  return {sent, log, notices};
}

let result = await trial('ok');
assert.equal(result.sent, 2, 'new speech must dispatch while old requests remain unacknowledged');
assert(!result.log.some(command => command.includes(' ack ')), 'host receipt must not fake completion');
for (const mode of ['throw', 'rejected', 'writefail']) {
  result = await trial(mode);
  assert.equal(result.sent, 1, 'uncertain/failed host operation must stop without a retry');
  assert(!result.log.some(command => command.includes('--receipt-ref')));
}
console.log('4 voice bridge host cases passed');
