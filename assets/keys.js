(()=>{
const KEYS=new Set(["ArrowUp","ArrowDown","PageUp","PageDown","Home","End"]);
function scroller(){
  const ms=document.querySelectorAll("[data-transcript-message]");
  for(let i=ms.length-1;i>=0;i--){
    let el=ms[i].parentElement;
    while(el&&el!==document.body){
      if(el.scrollHeight>el.clientHeight+1){
        const o=getComputedStyle(el).overflowY;
        if((o==="auto"||o==="scroll")&&el.getClientRects().length)return el;
      }
      el=el.parentElement;
    }
  }
  return null;
}
function permissionPrompt(){
  for(const c of document.querySelectorAll('[class*="permissionRequestContainer_"]'))
    if(c.getClientRects().length)return c;
  return null;
}
// Used by the patched focus_last_message case in index.js: with no prompt, Ctrl+Alt+Z focuses the chat input.
window.foolHasPrompt=(visibleOnly)=>[...document.querySelectorAll('[class*="permissionRequestContainer_"]')]
  .some(c=>!visibleOnly||c.getClientRects().length>0);
function focusReason(c){
  const el=c.querySelector('[class*="rejectMessageInput_"] [contenteditable]');
  if(!el)return;
  el.focus();
  const r=document.createRange();
  r.selectNodeContents(el);
  r.collapse(false);
  const s=getSelection();
  s.removeAllRanges();
  s.addRange(r);
}
function answer(c,action){
  if(action==="reason")return focusReason(c);
  const row=c.querySelector('[class*="buttonContainer_"]');
  const btns=row?[...row.querySelectorAll(":scope > button")]:[];
  const hasNo=!!(row&&row.querySelector('[class*="rejectMessageInput_"]'));
  if(action==="accept"){
    const yes=btns[0];
    if(yes&&!(hasNo&&btns.length===1)&&!yes.disabled)yes.click();
  }else if(hasNo&&btns.length){
    btns[btns.length-1].click();
  }else{
    c.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",code:"Escape",bubbles:true,cancelable:true}));
  }
}
window.addEventListener("message",(ev)=>{
  const d=ev.data;
  const req=d&&d.type==="from-extension"&&d.message&&d.message.request;
  const action=req&&req.type==="focus_last_message"&&req.fool;
  if(!action)return;
  if(action==="reason"&&!window.foolHasPrompt(false))return;
  const t0=Date.now();
  const tick=()=>{
    const c=permissionPrompt();
    if(c){
      answer(c,action);
      if(action!=="reason"||Date.now()-t0>400)return;
    }else if(Date.now()-t0>1500)return;
    setTimeout(tick,50);
  };
  setTimeout(tick,50);
});
const ACTIONS={Enter:"accept",NumpadEnter:"accept",Backspace:"reject",KeyZ:"reason"};
window.addEventListener("keydown",(e)=>{
  if(!e.ctrlKey||!e.altKey||e.shiftKey||e.metaKey)return;
  if(ACTIONS[e.code]){
    const c=permissionPrompt();
    if(!c)return;
    e.preventDefault();
    e.stopImmediatePropagation();
    answer(c,ACTIONS[e.code]);
    return;
  }
  if(e.code==="KeyH"){
    const b=document.querySelector('button[aria-label="Session history"]');
    if(!b)return;
    e.preventDefault();
    e.stopImmediatePropagation();
    b.click();
    return;
  }
  if(!KEYS.has(e.key))return;
  const el=scroller();
  if(!el)return;
  e.preventDefault();
  e.stopImmediatePropagation();
  const page=Math.max(el.clientHeight-60,60);
  let top=el.scrollTop;
  switch(e.key){
    case"ArrowUp":top-=80;break;
    case"ArrowDown":top+=80;break;
    case"PageUp":top-=page;break;
    case"PageDown":top+=page;break;
    case"Home":top=0;break;
    case"End":top=el.scrollHeight;break;
  }
  el.scrollTo({top,behavior:"instant"});
},true);
})();
