// Codex functions.exec host adapter, NOT a Node/browser background service.
// Before running, the human must have authorized delivering their voice to the
// exact operator thread. The caller defines VOICE_BRIDGE_CONFIG with absolute
// repository/inbox paths, threadId and a bounded durationSeconds (<=300).
// Requires the host tools object plus notify/text/setTimeout; no credentials.
const c = VOICE_BRIDGE_CONFIG;
if (!/^[a-f0-9-]{36}$/.test(c.threadId) || !Number.isFinite(c.durationSeconds)
    || c.durationSeconds <= 0 || c.durationSeconds > 300) {
  throw Error('Exact thread and finite duration <=300s required');
}
const quote = value => "'" + String(value).replaceAll("'", "''") + "'";
const started = Date.now();
let delivered = 0;
while (Date.now() - started < c.durationSeconds * 1000) {
  let result = await tools.exec_command({
    cmd: `python -X utf8 -m skyrim_autotest.voice_inbox --inbox ${quote(c.inbox)} --thread ${quote(c.threadId)} claim --wait 30`,
    workdir: c.repository, yield_time_ms: 1000, max_output_tokens: 12000
  });
  while (result.session_id) {
    result = await tools.write_stdin({session_id: result.session_id,
      chars: '', yield_time_ms: 1000, max_output_tokens: 12000});
  }
  let claim;
  try { claim = JSON.parse(result.output.trim().split(/\r?\n/).at(-1)); }
  catch { notify({bridge: 'blocked', reason: 'Inbox output incomplete/unreadable'}); break; }
  if (claim.status === 'blocked') { notify(claim); break; }
  if (claim.status === 'claimed') {
    // Deliver a pointer only, not an implicit command to act or retry.
    const receipt = await tools.mcp__codex_app__send_message_to_thread({
      threadId: c.threadId,
      prompt: `New ASR delivery from the owner-authorized active voice bridge. ` +
        `Read ${c.inbox}/state.json pending, requiring claimId=${claim.id}, ` +
        `recordsSha256=${claim.recordsSha256}, threadId=${c.threadId}, ` +
        `seq=${claim.firstSeq}..${claim.lastSeq}. Treat speech as possibly erroneous ` +
        `ASR; handle the owner's clear authorized request once or clarify. Reply ` +
        `in this operator chat without a typed reminder. Retain a local processing/` +
        `reply reference, then ack the exact claim using voice_inbox. Never replay ` +
        `uncertain/prior actions or restart the manual game/MO2/VR driver. ` +
        `Primary replies are text, short speech exceptionally. Screenshot requests ` +
        `require announced countdown and an actual verified image. Give-items ` +
        `defaults to inventory. Record ASR-to-response latency separately from ` +
        `unknown speech-onset time. This bridge works only while its host turn is active.`
    });
    const accepted = !receipt.isError;
    const meta = {claimId: claim.id, threadId: c.threadId,
      firstSeq: claim.firstSeq, lastSeq: claim.lastSeq,
      atUtc: new Date().toISOString(), accepted, receipt};
    await tools.apply_patch(`*** Begin Patch\n*** Add File: ${c.inbox}/dispatch-${claim.id}.json\n+${JSON.stringify(meta)}\n*** End Patch`);
    delivered++;
    notify({bridge: 'voice_dispatched', claimId: claim.id,
      firstSeq: claim.firstSeq, lastSeq: claim.lastSeq, accepted, atUtc: meta.atUtc});
    if (!accepted) break; // No blind retry of failed/ambiguous host delivery.
  } else if (claim.status === 'pending_review') {
    // Same claim already exists. The operator must reconcile/process/ack it;
    // sending it again might duplicate a game action after an uncertain reply.
    await new Promise(resolve => setTimeout(resolve, 1000));
  } else if (claim.status !== 'quiet') {
    notify({bridge: 'blocked', reason: 'Unknown inbox status'}); break;
  }
}
text({bridge: 'bounded_watch_ended', delivered,
  seconds: Math.round((Date.now() - started) / 1000)});
