(()=>{
const meta=document.getElementById("fool-pdf-page");
let page=meta?parseInt(meta.getAttribute("content"),10):0;
const load=PDFViewerApplication.load;
PDFViewerApplication.load=function(){
  if(page)this.initialBookmark="page="+page;
  return load.apply(this,arguments);
};
window.addEventListener("message",(e)=>{
  page=0;
  if(!e.data||e.data.type!=="fool-goto")return;
  e.stopImmediatePropagation();
  PDFViewerApplication.page=e.data.page;
});
})();
