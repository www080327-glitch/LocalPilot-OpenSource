// Never opens a QQ WebSocket, polls iLink, logs in, or calls a real platform/model.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { Bridge as QQBridge, QQClient, State as QQState, senderId as qqSender } from '../integrations/qq-bridge/bridge.mjs';
import { Bridge as WXBridge, ILink, State as WXState, senderId as wxSender } from '../integrations/wechat-ilink-bridge/bridge.mjs';

const cfg = JSON.parse(process.env.LP_TEST_SCENARIO);
assert.equal(new URL(cfg.adapter).hostname, '127.0.0.1');
const sentQQ = [], sentWX = [];
const mock = http.createServer(async (req, res) => {
  let raw = ''; for await (const chunk of req) raw += chunk;
  const body = raw ? JSON.parse(raw) : {};
  let data;
  if (req.url === '/app/getAppAccessToken') data = {access_token:'FAKE_QQ_TOKEN',expires_in:'7200'};
  else if (req.url.startsWith('/v2/users/')) {sentQQ.push({path:req.url,body});data={id:'mock-reply'};}
  else if (req.url === '/ilink/bot/sendmessage') {sentWX.push(body.msg);data={};}
  else {res.writeHead(404);return res.end('{}');}
  res.writeHead(200);res.end(JSON.stringify(data));
});
await new Promise(resolve=>mock.listen(0,'127.0.0.1',resolve));
const origin='http://127.0.0.1:'+mock.address().port;
const qs=new QQState(path.join(cfg.state,'qq'),'123456789');
const ws=new WXState(path.join(cfg.state,'wechat'));
ws.data.account={botId:'bot-1',token:'FAKE_WECHAT_TOKEN',baseUrl:origin};ws.save();
const makeQQ=store=>new QQBridge(store,new QQClient('123456789','FAKE_QQ_SECRET_FOR_TESTS',{base:origin,mock:true}),
  {key:cfg.qkey,allowed:[qqSender('123456789','peer-a'),qqSender('123456789','peer-b')],adapterUrl:cfg.adapter,emit:()=>{}});
const q=makeQQ(qs);
const w=new WXBridge(ws,new ILink({baseUrl:origin,mock:true}),{key:cfg.wkey,approvalKey:cfg.approval,
  allowed:[wxSender('peer-a'),wxSender('peer-b')],approvers:[wxSender('peer-a')],adapterUrl:cfg.adapter,emit:()=>{}});
const qe=(id,text='list',peer='peer-a')=>({op:0,t:'C2C_MESSAGE_CREATE',d:{id,author:{user_openid:peer},
  content:text,message_type:0,timestamp:new Date().toISOString()}});
const we=(id,text='list',peer='peer-a')=>({message_type:1,message_state:2,message_id:id,from_user_id:peer,
  to_user_id:'bot-1',context_token:'context-'+peer,item_list:[{type:1,text_item:{text}}]});
let index=0;
async function settle(bridge,store,task,kind){
  for(let i=0;i<80;i++){
    if(!['processing','submitting'].includes(task.status))return;
    await new Promise(resolve=>setTimeout(resolve,25));
    const text='/lp status '+task.taskId;
    await bridge.handle(kind==='q'?qe('query-'+(++index),text):we('query-'+(++index),text));
  }
  assert.fail('isolated task did not settle');
}
try {
  await q.handle(qe('unauthorized','list','outsider'));
  assert.equal(Object.keys(qs.data.messages).length,0);
  const first=qe('same-message');
  await q.handle(first);
  const qa=Object.values(qs.data.messages).find(r=>r.kind==='task');
  await settle(q,qs,qa,'q');assert.equal(qa.status,'completed');
  assert.match(sentQQ.at(-1).body.content,/marker.txt/);
  const qcount=sentQQ.length;await q.handle(first);assert.equal(sentQQ.length,qcount);
  await w.handle(we('9007199254740993'));
  const wa=Object.values(ws.data.messages).find(r=>!r.kind);
  await settle(w,ws,wa,'w');assert.equal(wa.status,'completed');
  assert.match(sentWX.at(-1).item_list[0].text_item.text,/marker.txt/);
  await Promise.all([q.handle(qe('other-sender','list','peer-b')),w.handle(we('other-sender','list','peer-b'))]);
  assert.ok(sentQQ.every(r=>r.path.includes('/peer-a/')||r.path.includes('/peer-b/')));
  assert.ok(sentWX.every(r=>r.context_token==='context-'+r.to_user_id));
  await w.handle(we('approval-task','approval'));
  const pending=Object.values(ws.data.messages).find(r=>r.messageId==='approval-task');
  await settle(w,ws,pending,'w');assert.equal(pending.status,'pending_approval');
  const approvalId=pending.approvalId;assert.ok(approvalId);
  await w.handle(we('approve-command',`/lp approve ${pending.taskId} ${approvalId} yes-1`));
  await settle(w,ws,pending,'w');assert.equal(pending.status,'completed');
  await w.handle(we('approve-duplicate',`/lp approve ${pending.taskId} ${approvalId} yes-1`));
  await w.handle(we('reject-task','reject'));
  const refused=Object.values(ws.data.messages).find(r=>r.messageId==='reject-task');
  await settle(w,ws,refused,'w');assert.equal(refused.status,'pending_approval');
  await w.handle(we('bad-approval',`/lp approve ${refused.taskId} stale wrong-1`));
  assert.equal(refused.status,'pending_approval');
  await w.handle(we('reject-command',`/lp reject ${refused.taskId} ${refused.approvalId} no-1 deny`));
  await settle(w,ws,refused,'w');assert.equal(refused.status,'rejected');
  await q.handle(qe('forbidden-approve','/lp approve anything anything anything'));
  assert.match(sentQQ.at(-1).body.content,/不支持审批/);
  qs.close();const reopened=new QQState(path.join(cfg.state,'qq'),'123456789');
  const before=sentQQ.length;await makeQQ(reopened).handle(first);assert.equal(sentQQ.length,before);reopened.close();
  assert.ok(!JSON.stringify([...sentQQ,...sentWX]).includes(cfg.qkey));
  console.log(JSON.stringify({dual_channel:'PASS',qq:'PASS',wechat:'PASS',approval:'PASS',reject:'PASS',dedupe:'PASS',restart:'PASS'}));
}finally{
  qs.close();ws.close();mock.closeAllConnections();await new Promise(resolve=>mock.close(resolve));
}
