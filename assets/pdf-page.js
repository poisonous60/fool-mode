(()=>{
const vscode=require("vscode");
const {PdfPreview}=require("./pdfPreview");
const pending=new Map();
const previews=new Set();
// setPage gets an fsPath (Windows: "e:\\a\\b.pdf"); previews know a Uri path ("/e:/a/b.pdf"). Compare as Uri paths, case-insensitive.
const key=(uriPath)=>uriPath.toLowerCase();
const html=PdfPreview.prototype.getWebviewContents;
PdfPreview.prototype.getWebviewContents=function(){
  previews.add(this);
  const k=key(this.resource.path);
  const page=pending.get(k);
  pending.delete(k);
  const out=html.call(this);
  return page?out.replace('<meta id="pdf-preview-config"',`<meta id="fool-pdf-page" content="${page}">$&`):out;
};
const activate=exports.activate;
exports.activate=function(context){
  activate(context);
  context.subscriptions.push(vscode.commands.registerCommand("pdfPreview.setPage",(fsPath,page)=>{
    page=parseInt(page,10);
    if(!fsPath||!(page>0))return false;
    const k=key(vscode.Uri.file(fsPath).path);
    let shown=false;
    for(const p of previews){
      if(p._previewState==="Disposed"){previews.delete(p);continue;}
      if(key(p.resource.path)!==k)continue;
      p.webviewEditor.webview.postMessage({type:"fool-goto",page});
      shown=true;
    }
    if(!shown)pending.set(k,page);
    return shown;
  }));
};
})();
