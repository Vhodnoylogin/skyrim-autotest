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
const inboxCommand = async command => {
  let result = await tools.exec_command({
    cmd: `python -X utf8 -m skyrim_autotest.voice_inbox --inbox ${quote(c.inbox)} --thread ${quote(c.threadId)} ${command}`,
    workdir: c.repository, yield_time_ms: 1000, max_output_tokens: 12000
  });
  while (result.session_id) {
    result = await tools.write_stdin({session_id: result.session_id,
      chars: '', yield_time_ms: 1000, max_output_tokens: 12000});
  }
  const value = JSON.parse(result.output.trim().split(/\r?\n/).at(-1));
  if (result.exit_code !== 0 || value.status === 'blocked') {
    throw Error(value.error || 'Inbox command failed');
  }
  return value;
};
let delivered = 0;
while (Date.now() - started < c.durationSeconds * 1000) {
  let claim;
  try { claim = await inboxCommand('admit --wait 2'); }
  catch (error) { notify({bridge: 'blocked', reason: String(error)}); break; }
  if (claim.status === 'received') {
    const exact = `--id ${quote(claim.id)} --sha256 ${quote(claim.recordsSha256)}`;
    try { await inboxCommand(`dispatch ${exact}`); }
    catch (error) { notify({bridge: 'blocked', reason: String(error)}); break; }
    // Deliver a pointer only, not an implicit command to act or retry.
    let receipt;
    try { receipt = await tools.mcp__codex_app__send_message_to_thread({
      threadId: c.threadId,
      prompt: `New ASR delivery from the owner-authorized active voice bridge. ` +
        `Read ${c.inbox}/state.json deliveries entry, requiring claimId=${claim.id}, ` +
        `recordsSha256=${claim.recordsSha256}, threadId=${c.threadId}, ` +
        `seq=${claim.firstSeq}..${claim.lastSeq}. Treat speech as possibly erroneous ` +
        `ASR; acknowledge receipt briefly in text before lengthy analysis. ` +
        `Record that actual first text reply with voice_inbox reply --id/--sha256/` +
        `--response-ref; do not mark action completion then. ` +
        `Only final complete speech may supply commands. Prefer short status replies ` +
        `and explicit screenshot requests before deferred analysis, preserving the ` +
        `order of game mutations. Handle the owner's clear authorized request once ` +
        `or clarify. Reply in this operator chat without a typed reminder. ` +
        `New speech can arrive before this request is completed. Received/host ` +
        `delivered do not mean executed. Retain a local processing/` +
        `reply reference, then ack the exact claim using voice_inbox. Never replay ` +
        `uncertain/prior actions or restart the manual game/MO2/VR driver. ` +
        `Primary replies are text, short speech exceptionally. Screenshot requests ` +
        `require announced countdown and an actual verified image. Give-items ` +
        `defaults to inventory. Record ASR-to-response latency separately from ` +
        `unknown speech-onset time. Record first text reply and action completion ` +
        `separately. This bridge works only while its host turn is active.`
    }); } catch (error) {
      notify({bridge: 'uncertain_host_delivery', claimId: claim.id, reason: String(error)});
      break; // Durable dispatching remains; never send this claim automatically again.
    }
    const accepted = !receipt.isError;
    const meta = {claimId: claim.id, threadId: c.threadId,
      firstSeq: claim.firstSeq, lastSeq: claim.lastSeq,
      atUtc: new Date().toISOString(), accepted, receipt};
    const receiptPath = `${c.inbox}/dispatch-${claim.id}.json`;
    const saved = await tools.apply_patch(`*** Begin Patch\n*** Add File: ${receiptPath}\n+${JSON.stringify(meta)}\n*** End Patch`);
    if (saved.isError) { notify({bridge: 'receipt_write_failed', claimId: claim.id}); break; }
    delivered++;
    notify({bridge: 'voice_dispatched', claimId: claim.id,
      firstSeq: claim.firstSeq, lastSeq: claim.lastSeq, accepted, atUtc: meta.atUtc});
    if (!accepted) break; // No blind retry of failed/ambiguous host delivery.
    try { await inboxCommand(`dispatch ${exact} --receipt-ref ${quote(receiptPath)}`); }
    catch (error) { notify({bridge: 'receipt_reconcile_required', claimId: claim.id, reason: String(error)}); break; }
  } else if (claim.status !== 'quiet') {
    notify({bridge: 'blocked', reason: 'Unknown inbox status'}); break;
  }
}
text({bridge: 'bounded_watch_ended', delivered,
  seconds: Math.round((Date.now() - started) / 1000)});
