(()=>{
const vscode=require("vscode");
const {PdfPreview}=require("./pdfPreview");
const pending=new Map();
const previews=new Set();
const html=PdfPreview.prototype.getWebviewContents;
PdfPreview.prototype.getWebviewContents=function(){
  previews.add(this);
  const page=pending.get(this.resource.path);
  pending.delete(this.resource.path);
  const out=html.call(this);
  return page?out.replace('<meta id="pdf-preview-config"',`<meta id="fool-pdf-page" content="${page}">$&`):out;
};
const activate=exports.activate;
exports.activate=function(context){
  activate(context);
  context.subscriptions.push(vscode.commands.registerCommand("pdfPreview.setPage",(fsPath,page)=>{
    page=parseInt(page,10);
    if(!fsPath||!(page>0))return false;
    let shown=false;
    for(const p of previews){
      if(p._previewState==="Disposed"){previews.delete(p);continue;}
      if(p.resource.path!==fsPath)continue;
      p.webviewEditor.webview.postMessage({type:"fool-goto",page});
      shown=true;
    }
    if(!shown)pending.set(fsPath,page);
    return shown;
  }));
};
})();
