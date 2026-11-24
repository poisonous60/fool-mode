(()=>{
window.addEventListener("keydown",(e)=>{
  if(!e.ctrlKey||!e.altKey||e.shiftKey||e.metaKey)return;
  const el=document.scrollingElement||document.documentElement;
  const page=Math.max(window.innerHeight-60,60);
  let top=el.scrollTop;
  switch(e.key){
    case"ArrowUp":top-=80;break;
    case"ArrowDown":top+=80;break;
    case"PageUp":top-=page;break;
    case"PageDown":top+=page;break;
    case"Home":top=0;break;
    case"End":top=el.scrollHeight;break;
    default:return;
  }
  e.preventDefault();
  e.stopImmediatePropagation();
  window.scrollTo({top,behavior:"instant"});
},true);
})();
