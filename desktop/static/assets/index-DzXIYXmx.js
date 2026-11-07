(function(){let e=document.createElement(`link`).relList;if(e&&e.supports&&e.supports(`modulepreload`))return;for(let e of document.querySelectorAll(`link[rel="modulepreload"]`))n(e);new MutationObserver(e=>{for(let t of e)if(t.type===`childList`)for(let e of t.addedNodes)e.tagName===`LINK`&&e.rel===`modulepreload`&&n(e)}).observe(document,{childList:!0,subtree:!0});function t(e){let t={};return e.integrity&&(t.integrity=e.integrity),e.referrerPolicy&&(t.referrerPolicy=e.referrerPolicy),t.credentials=e.crossOrigin===`use-credentials`?`include`:e.crossOrigin===`anonymous`?`omit`:`same-origin`,t}function n(e){if(e.ep)return;e.ep=!0;let n=t(e);fetch(e.href,n)}})();var e=globalThis,t=e.ShadowRoot&&(e.ShadyCSS===void 0||e.ShadyCSS.nativeShadow)&&`adoptedStyleSheets`in Document.prototype&&`replace`in CSSStyleSheet.prototype,n=Symbol(),r=new WeakMap,i=class{constructor(e,t,r){if(this._$cssResult$=!0,r!==n)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=e,this.t=t}get styleSheet(){let e=this.o,n=this.t;if(t&&e===void 0){let t=n!==void 0&&n.length===1;t&&(e=r.get(n)),e===void 0&&((this.o=e=new CSSStyleSheet).replaceSync(this.cssText),t&&r.set(n,e))}return e}toString(){return this.cssText}},a=e=>new i(typeof e==`string`?e:e+``,void 0,n),o=(n,r)=>{if(t)n.adoptedStyleSheets=r.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let t of r){let r=document.createElement(`style`),i=e.litNonce;i!==void 0&&r.setAttribute(`nonce`,i),r.textContent=t.cssText,n.appendChild(r)}},s=t?e=>e:e=>e instanceof CSSStyleSheet?(e=>{let t=``;for(let n of e.cssRules)t+=n.cssText;return a(t)})(e):e,{is:c,defineProperty:l,getOwnPropertyDescriptor:u,getOwnPropertyNames:d,getOwnPropertySymbols:f,getPrototypeOf:p}=Object,m=globalThis,ee=m.trustedTypes,te=ee?ee.emptyScript:``,ne=m.reactiveElementPolyfillSupport,h=(e,t)=>e,re={toAttribute(e,t){switch(t){case Boolean:e=e?te:null;break;case Object:case Array:e=e==null?e:JSON.stringify(e)}return e},fromAttribute(e,t){let n=e;switch(t){case Boolean:n=e!==null;break;case Number:n=e===null?null:Number(e);break;case Object:case Array:try{n=JSON.parse(e)}catch{n=null}}return n}},ie=(e,t)=>!c(e,t),ae={attribute:!0,type:String,converter:re,reflect:!1,useDefault:!1,hasChanged:ie};Symbol.metadata??=Symbol(`metadata`),m.litPropertyMetadata??=new WeakMap;var g=class extends HTMLElement{static addInitializer(e){this._$Ei(),(this.l??=[]).push(e)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(e,t=ae){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(e)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(e,t),!t.noAccessor){let n=Symbol(),r=this.getPropertyDescriptor(e,n,t);r!==void 0&&l(this.prototype,e,r)}}static getPropertyDescriptor(e,t,n){let{get:r,set:i}=u(this.prototype,e)??{get(){return this[t]},set(e){this[t]=e}};return{get:r,set(t){let a=r?.call(this);i?.call(this,t),this.requestUpdate(e,a,n)},configurable:!0,enumerable:!0}}static getPropertyOptions(e){return this.elementProperties.get(e)??ae}static _$Ei(){if(this.hasOwnProperty(h(`elementProperties`)))return;let e=p(this);e.finalize(),e.l!==void 0&&(this.l=[...e.l]),this.elementProperties=new Map(e.elementProperties)}static finalize(){if(this.hasOwnProperty(h(`finalized`)))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(h(`properties`))){let e=this.properties,t=[...d(e),...f(e)];for(let n of t)this.createProperty(n,e[n])}let e=this[Symbol.metadata];if(e!==null){let t=litPropertyMetadata.get(e);if(t!==void 0)for(let[e,n]of t)this.elementProperties.set(e,n)}this._$Eh=new Map;for(let[e,t]of this.elementProperties){let n=this._$Eu(e,t);n!==void 0&&this._$Eh.set(n,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(e){let t=[];if(Array.isArray(e)){let n=new Set(e.flat(1/0).reverse());for(let e of n)t.unshift(s(e))}else e!==void 0&&t.push(s(e));return t}static _$Eu(e,t){let n=t.attribute;return!1===n?void 0:typeof n==`string`?n:typeof e==`string`?e.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(e=>this.enableUpdating=e),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(e=>e(this))}addController(e){(this._$EO??=new Set).add(e),this.renderRoot!==void 0&&this.isConnected&&e.hostConnected?.()}removeController(e){this._$EO?.delete(e)}_$E_(){let e=new Map,t=this.constructor.elementProperties;for(let n of t.keys())this.hasOwnProperty(n)&&(e.set(n,this[n]),delete this[n]);e.size>0&&(this._$Ep=e)}createRenderRoot(){let e=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return o(e,this.constructor.elementStyles),e}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(e=>e.hostConnected?.())}enableUpdating(e){}disconnectedCallback(){this._$EO?.forEach(e=>e.hostDisconnected?.())}attributeChangedCallback(e,t,n){this._$AK(e,n)}_$ET(e,t){let n=this.constructor.elementProperties.get(e),r=this.constructor._$Eu(e,n);if(r!==void 0&&!0===n.reflect){let i=(n.converter?.toAttribute===void 0?re:n.converter).toAttribute(t,n.type);this._$Em=e,i==null?this.removeAttribute(r):this.setAttribute(r,i),this._$Em=null}}_$AK(e,t){let n=this.constructor,r=n._$Eh.get(e);if(r!==void 0&&this._$Em!==r){let e=n.getPropertyOptions(r),i=typeof e.converter==`function`?{fromAttribute:e.converter}:e.converter?.fromAttribute===void 0?re:e.converter;this._$Em=r;let a=i.fromAttribute(t,e.type);this[r]=a??this._$Ej?.get(r)??a,this._$Em=null}}requestUpdate(e,t,n,r=!1,i){if(e!==void 0){let a=this.constructor;if(!1===r&&(i=this[e]),n??=a.getPropertyOptions(e),!((n.hasChanged??ie)(i,t)||n.useDefault&&n.reflect&&i===this._$Ej?.get(e)&&!this.hasAttribute(a._$Eu(e,n))))return;this.C(e,t,n)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(e,t,{useDefault:n,reflect:r,wrapped:i},a){n&&!(this._$Ej??=new Map).has(e)&&(this._$Ej.set(e,a??t??this[e]),!0!==i||a!==void 0)||(this._$AL.has(e)||(this.hasUpdated||n||(t=void 0),this._$AL.set(e,t)),!0===r&&this._$Em!==e&&(this._$Eq??=new Set).add(e))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let e=this.scheduleUpdate();return e!=null&&await e,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[e,t]of this._$Ep)this[e]=t;this._$Ep=void 0}let e=this.constructor.elementProperties;if(e.size>0)for(let[t,n]of e){let{wrapped:e}=n,r=this[t];!0!==e||this._$AL.has(t)||r===void 0||this.C(t,void 0,n,r)}}let e=!1,t=this._$AL;try{e=this.shouldUpdate(t),e?(this.willUpdate(t),this._$EO?.forEach(e=>e.hostUpdate?.()),this.update(t)):this._$EM()}catch(t){throw e=!1,this._$EM(),t}e&&this._$AE(t)}willUpdate(e){}_$AE(e){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(e)),this.updated(e)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(e){return!0}update(e){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(e){}firstUpdated(e){}};g.elementStyles=[],g.shadowRootOptions={mode:`open`},g[h(`elementProperties`)]=new Map,g[h(`finalized`)]=new Map,ne?.({ReactiveElement:g}),(m.reactiveElementVersions??=[]).push(`2.1.2`);var oe=globalThis,se=e=>e,_=oe.trustedTypes,ce=_?_.createPolicy(`lit-html`,{createHTML:e=>e}):void 0,v=`$lit$`,y=`lit$${Math.random().toFixed(9).slice(2)}$`,le=`?`+y,ue=`<${le}>`,b=document,x=()=>b.createComment(``),S=e=>e===null||typeof e!=`object`&&typeof e!=`function`,de=Array.isArray,fe=e=>de(e)||typeof e?.[Symbol.iterator]==`function`,pe=`[ 	
\f\r]`,C=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,me=/-->/g,he=/>/g,w=RegExp(`>|${pe}(?:([^\\s"'>=/]+)(${pe}*=${pe}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,`g`),ge=/'/g,_e=/"/g,ve=/^(?:script|style|textarea|title)$/i,T=(e=>(t,...n)=>({_$litType$:e,strings:t,values:n}))(1),E=Symbol.for(`lit-noChange`),D=Symbol.for(`lit-nothing`),ye=new WeakMap,O=b.createTreeWalker(b,129);function be(e,t){if(!de(e)||!e.hasOwnProperty(`raw`))throw Error(`invalid template strings array`);return ce===void 0?t:ce.createHTML(t)}var xe=(e,t)=>{let n=e.length-1,r=[],i,a=t===2?`<svg>`:t===3?`<math>`:``,o=C;for(let t=0;t<n;t++){let n=e[t],s,c,l=-1,u=0;for(;u<n.length&&(o.lastIndex=u,c=o.exec(n),c!==null);)u=o.lastIndex,o===C?c[1]===`!--`?o=me:c[1]===void 0?c[2]===void 0?c[3]!==void 0&&(o=w):(ve.test(c[2])&&(i=RegExp(`</`+c[2],`g`)),o=w):o=he:o===w?c[0]===`>`?(o=i??C,l=-1):c[1]===void 0?l=-2:(l=o.lastIndex-c[2].length,s=c[1],o=c[3]===void 0?w:c[3]===`"`?_e:ge):o===_e||o===ge?o=w:o===me||o===he?o=C:(o=w,i=void 0);let d=o===w&&e[t+1].startsWith(`/>`)?` `:``;a+=o===C?n+ue:l>=0?(r.push(s),n.slice(0,l)+v+n.slice(l)+y+d):n+y+(l===-2?t:d)}return[be(e,a+(e[n]||`<?>`)+(t===2?`</svg>`:t===3?`</math>`:``)),r]},Se=class e{constructor({strings:t,_$litType$:n},r){let i;this.parts=[];let a=0,o=0,s=t.length-1,c=this.parts,[l,u]=xe(t,n);if(this.el=e.createElement(l,r),O.currentNode=this.el.content,n===2||n===3){let e=this.el.content.firstChild;e.replaceWith(...e.childNodes)}for(;(i=O.nextNode())!==null&&c.length<s;){if(i.nodeType===1){if(i.hasAttributes())for(let e of i.getAttributeNames())if(e.endsWith(v)){let t=u[o++],n=i.getAttribute(e).split(y),r=/([.?@])?(.*)/.exec(t);c.push({type:1,index:a,name:r[2],strings:n,ctor:r[1]===`.`?we:r[1]===`?`?Te:r[1]===`@`?Ee:j}),i.removeAttribute(e)}else e.startsWith(y)&&(c.push({type:6,index:a}),i.removeAttribute(e));if(ve.test(i.tagName)){let e=i.textContent.split(y),t=e.length-1;if(t>0){i.textContent=_?_.emptyScript:``;for(let n=0;n<t;n++)i.append(e[n],x()),O.nextNode(),c.push({type:2,index:++a});i.append(e[t],x())}}}else if(i.nodeType===8){if(i.data===le)c.push({type:2,index:a});else{let e=-1;for(;(e=i.data.indexOf(y,e+1))!==-1;)c.push({type:7,index:a}),e+=y.length-1}}a++}}static createElement(e,t){let n=b.createElement(`template`);return n.innerHTML=e,n}};function k(e,t,n=e,r){if(t===E)return t;let i=r===void 0?n._$Cl:n._$Co?.[r],a=S(t)?void 0:t._$litDirective$;return i?.constructor!==a&&(i?._$AO?.(!1),a===void 0?i=void 0:(i=new a(e),i._$AT(e,n,r)),r===void 0?n._$Cl=i:(n._$Co??=[])[r]=i),i!==void 0&&(t=k(e,i._$AS(e,t.values),i,r)),t}var Ce=class{constructor(e,t){this._$AV=[],this._$AN=void 0,this._$AD=e,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(e){let{el:{content:t},parts:n}=this._$AD,r=(e?.creationScope??b).importNode(t,!0);O.currentNode=r;let i=O.nextNode(),a=0,o=0,s=n[0];for(;s!==void 0;){if(a===s.index){let t;s.type===2?t=new A(i,i.nextSibling,this,e):s.type===1?t=new s.ctor(i,s.name,s.strings,this,e):s.type===6&&(t=new De(i,this,e)),this._$AV.push(t),s=n[++o]}a!==s?.index&&(i=O.nextNode(),a++)}return O.currentNode=b,r}p(e){let t=0;for(let n of this._$AV)n!==void 0&&(n.strings===void 0?n._$AI(e[t]):(n._$AI(e,n,t),t+=n.strings.length-2)),t++}},A=class e{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(e,t,n,r){this.type=2,this._$AH=D,this._$AN=void 0,this._$AA=e,this._$AB=t,this._$AM=n,this.options=r,this._$Cv=r?.isConnected??!0}get parentNode(){let e=this._$AA.parentNode,t=this._$AM;return t!==void 0&&e?.nodeType===11&&(e=t.parentNode),e}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(e,t=this){e=k(this,e,t),S(e)?e===D||e==null||e===``?(this._$AH!==D&&this._$AR(),this._$AH=D):e!==this._$AH&&e!==E&&this._(e):e._$litType$===void 0?e.nodeType===void 0?fe(e)?this.k(e):this._(e):this.T(e):this.$(e)}O(e){return this._$AA.parentNode.insertBefore(e,this._$AB)}T(e){this._$AH!==e&&(this._$AR(),this._$AH=this.O(e))}_(e){this._$AH!==D&&S(this._$AH)?this._$AA.nextSibling.data=e:this.T(b.createTextNode(e)),this._$AH=e}$(e){let{values:t,_$litType$:n}=e,r=typeof n==`number`?this._$AC(e):(n.el===void 0&&(n.el=Se.createElement(be(n.h,n.h[0]),this.options)),n);if(this._$AH?._$AD===r)this._$AH.p(t);else{let e=new Ce(r,this),n=e.u(this.options);e.p(t),this.T(n),this._$AH=e}}_$AC(e){let t=ye.get(e.strings);return t===void 0&&ye.set(e.strings,t=new Se(e)),t}k(t){de(this._$AH)||(this._$AH=[],this._$AR());let n=this._$AH,r,i=0;for(let a of t)i===n.length?n.push(r=new e(this.O(x()),this.O(x()),this,this.options)):r=n[i],r._$AI(a),i++;i<n.length&&(this._$AR(r&&r._$AB.nextSibling,i),n.length=i)}_$AR(e=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);e!==this._$AB;){let t=se(e).nextSibling;se(e).remove(),e=t}}setConnected(e){this._$AM===void 0&&(this._$Cv=e,this._$AP?.(e))}},j=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(e,t,n,r,i){this.type=1,this._$AH=D,this._$AN=void 0,this.element=e,this.name=t,this._$AM=r,this.options=i,n.length>2||n[0]!==``||n[1]!==``?(this._$AH=Array(n.length-1).fill(new String),this.strings=n):this._$AH=D}_$AI(e,t=this,n,r){let i=this.strings,a=!1;if(i===void 0)e=k(this,e,t,0),a=!S(e)||e!==this._$AH&&e!==E,a&&(this._$AH=e);else{let r=e,o,s;for(e=i[0],o=0;o<i.length-1;o++)s=k(this,r[n+o],t,o),s===E&&(s=this._$AH[o]),a||=!S(s)||s!==this._$AH[o],s===D?e=D:e!==D&&(e+=(s??``)+i[o+1]),this._$AH[o]=s}a&&!r&&this.j(e)}j(e){e===D?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,e??``)}},we=class extends j{constructor(){super(...arguments),this.type=3}j(e){this.element[this.name]=e===D?void 0:e}},Te=class extends j{constructor(){super(...arguments),this.type=4}j(e){this.element.toggleAttribute(this.name,!!e&&e!==D)}},Ee=class extends j{constructor(e,t,n,r,i){super(e,t,n,r,i),this.type=5}_$AI(e,t=this){if((e=k(this,e,t,0)??D)===E)return;let n=this._$AH,r=e===D&&n!==D||e.capture!==n.capture||e.once!==n.once||e.passive!==n.passive,i=e!==D&&(n===D||r);r&&this.element.removeEventListener(this.name,this,n),i&&this.element.addEventListener(this.name,this,e),this._$AH=e}handleEvent(e){typeof this._$AH==`function`?this._$AH.call(this.options?.host??this.element,e):this._$AH.handleEvent(e)}},De=class{constructor(e,t,n){this.element=e,this.type=6,this._$AN=void 0,this._$AM=t,this.options=n}get _$AU(){return this._$AM._$AU}_$AI(e){k(this,e)}},Oe={M:v,P:y,A:le,C:1,L:xe,R:Ce,D:fe,V:k,I:A,H:j,N:Te,U:Ee,B:we,F:De},ke=oe.litHtmlPolyfillSupport;ke?.(Se,A),(oe.litHtmlVersions??=[]).push(`3.3.3`);var Ae=(e,t,n)=>{let r=n?.renderBefore??t,i=r._$litPart$;if(i===void 0){let e=n?.renderBefore??null;r._$litPart$=i=new A(t.insertBefore(x(),e),e,void 0,n??{})}return i._$AI(e),i},je=globalThis,M=class extends g{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let e=super.createRenderRoot();return this.renderOptions.renderBefore??=e.firstChild,e}update(e){let t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(e),this._$Do=Ae(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return E}};M._$litElement$=!0,M.finalized=!0,je.litElementHydrateSupport?.({LitElement:M});var Me=je.litElementPolyfillSupport;Me?.({LitElement:M}),(je.litElementVersions??=[]).push(`4.2.2`);var Ne=class extends M{createRenderRoot(){return this}render(){return T`
      <div class="backdrop" aria-hidden="true">
        <span class="orb orb--indigo"></span>
        <span class="orb orb--violet"></span>
        <span class="orb orb--teal"></span>
        <span class="grain"></span>
      </div>
    `}};customElements.define(`app-backdrop`,Ne);var Pe={ATTRIBUTE:1,CHILD:2,PROPERTY:3,BOOLEAN_ATTRIBUTE:4,EVENT:5,ELEMENT:6},Fe=e=>(...t)=>({_$litDirective$:e,values:t}),Ie=class{constructor(e){}get _$AU(){return this._$AM._$AU}_$AT(e,t,n){this._$Ct=e,this._$AM=t,this._$Ci=n}_$AS(e,t){return this.update(e,t)}update(e,t){return this.render(...t)}},{I:Le}=Oe,Re=e=>e,ze=()=>document.createComment(``),N=(e,t,n)=>{let r=e._$AA.parentNode,i=t===void 0?e._$AB:t._$AA;if(n===void 0)n=new Le(r.insertBefore(ze(),i),r.insertBefore(ze(),i),e,e.options);else{let t=n._$AB.nextSibling,a=n._$AM,o=a!==e;if(o){let t;n._$AQ?.(e),n._$AM=e,n._$AP!==void 0&&(t=e._$AU)!==a._$AU&&n._$AP(t)}if(t!==i||o){let e=n._$AA;for(;e!==t;){let t=Re(e).nextSibling;Re(r).insertBefore(e,i),e=t}}}return n},P=(e,t,n=e)=>(e._$AI(t,n),e),Be={},Ve=(e,t=Be)=>e._$AH=t,He=e=>e._$AH,Ue=e=>{e._$AR(),e._$AA.remove()},We=(e,t,n)=>{let r=new Map;for(let i=t;i<=n;i++)r.set(e[i],i);return r},F=Fe(class extends Ie{constructor(e){if(super(e),e.type!==Pe.CHILD)throw Error(`repeat() can only be used in text expressions`)}dt(e,t,n){let r;n===void 0?n=t:t!==void 0&&(r=t);let i=[],a=[],o=0;for(let t of e)i[o]=r?r(t,o):o,a[o]=n(t,o),o++;return{values:a,keys:i}}render(e,t,n){return this.dt(e,t,n).values}update(e,[t,n,r]){let i=He(e),{values:a,keys:o}=this.dt(t,n,r);if(!Array.isArray(i))return this.ut=o,a;let s=this.ut??=[],c=[],l,u,d=0,f=i.length-1,p=0,m=a.length-1;for(;d<=f&&p<=m;)if(i[d]===null)d++;else if(i[f]===null)f--;else if(s[d]===o[p])c[p]=P(i[d],a[p]),d++,p++;else if(s[f]===o[m])c[m]=P(i[f],a[m]),f--,m--;else if(s[d]===o[m])c[m]=P(i[d],a[m]),N(e,c[m+1],i[d]),d++,m--;else if(s[f]===o[p])c[p]=P(i[f],a[p]),N(e,i[d],i[f]),f--,p++;else if(l===void 0&&(l=We(o,p,m),u=We(s,d,f)),l.has(s[d])){if(l.has(s[f])){let t=u.get(o[p]),n=t===void 0?null:i[t];if(n===null){let t=N(e,i[d]);P(t,a[p]),c[p]=t}else c[p]=P(n,a[p]),N(e,i[d],n),i[t]=null;p++}else Ue(i[f]),f--}else Ue(i[d]),d++;for(;p<=m;){let t=N(e,c[m+1]);P(t,a[p]),c[p++]=t}for(;d<=f;){let e=i[d++];e!==null&&Ue(e)}return this.ut=o,Ve(e,c),E}});async function I(e,t){let n;try{n=await fetch(e,{method:`POST`,headers:{"Content-Type":`application/json`},body:JSON.stringify(t===void 0?{}:t)})}catch(e){throw Error(`Network error: ${e.message}`)}let r=null;try{r=await n.json()}catch{r=null}if(!n.ok){let e=r&&(r.error||r.message)?r.error||r.message:`Request failed (${n.status})`;throw Error(e)}return r}async function Ge(e){let t=e?`?bridgeId=${encodeURIComponent(e)}`:``,n=await fetch(`/api/state${t}`,{headers:{Accept:`application/json`}});if(!n.ok)throw Error(`state request failed (${n.status})`);return n.json()}async function Ke(){let e=await fetch(`/api/sessions`,{headers:{Accept:`application/json`}});if(!e.ok)throw Error(`sessions request failed (${e.status})`);return e.json()}async function qe(e){let t=e?`?bridgeId=${encodeURIComponent(e)}`:``,n=await fetch(`/api/history${t}`,{headers:{Accept:`application/json`}});if(!n.ok)throw Error(`history request failed (${n.status})`);return n.json()}async function Je(e,t){return I(`/api/complete`,{...e?{bridgeId:e}:{},text:t})}var Ye=1e3,Xe=8e3,Ze=4600,Qe=5e3,$e={read:T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/></svg>`,edit:T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20l4-1 10-10-3-3L5 16z"/><path d="M14 6l3 3M4 20l1-4"/></svg>`,execute:T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 6l6 6-6 6M13 18h6"/></svg>`,search:T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>`,think:T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 1 3.5 10.9c-.4.3-.5.7-.5 1.1H9c0-.4-.1-.8-.5-1.1A6 6 0 0 1 12 3z"/></svg>`,fetch:T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>`,other:T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12l-8-4.5M12 12v9"/></svg>`},et=T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"/><path d="M9 12l2 2 4-4"/></svg>`,tt=T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>`;T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/><circle cx="12" cy="12" r="3.2"/></svg>`;var nt=T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"/></svg>`,rt=T`<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>`,it=T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h14v16H5z"/><path d="M8 9h8M8 13h8M8 17h5"/></svg>`,at=T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`,ot=T`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 6.7"/><path d="M20 4v7h-7"/></svg>`;function st(e){let t=Number(e);if(!Number.isFinite(t)||t<0)return`—`;if(t<1e3)return String(Math.round(t));if(t<1e6){let e=t/1e3;return`${e>=100?Math.round(e):lt(e.toFixed(1))}k`}return`${lt((t/1e6).toFixed(1))}m`}function ct(e){if(!e||typeof e.amount!=`number`)return``;let t=typeof e.currency==`string`?e.currency.toUpperCase():``;try{return new Intl.NumberFormat(void 0,{style:`currency`,currency:t,maximumFractionDigits:4}).format(e.amount)}catch{return`${t} ${e.amount.toFixed(4)}`.trim()}}function lt(e){return String(e).replace(/\.0$/,``)}function ut(e){return typeof e.sessionUpdate==`string`?e.sessionUpdate:typeof e.type==`string`?e.type:e.toolCallId&&typeof e.status==`string`?`tool_call_update`:e.toolCallId?`tool_call`:``}function L(e){if(!e)return``;if(typeof e==`string`)return e;if(Array.isArray(e))return e.map(L).filter(Boolean).join(`
`);if(typeof e==`object`){if(typeof e.text==`string`)return e.text;if(e.content)return L(e.content)}return``}function dt(e){let t=typeof e==`string`?e:String(e||``),n=/<context\b([^>]*)>/i.exec(t),r=n?n[1]:``,i=/\bname=["']([^"']+)["']/i.exec(r)?.[1]||``,a=/\bfrom=["']([^"']+)["']/i.exec(r)?.[1]||``;return{text:t.replace(/<context\b[^>]*?\/?>/gi,``).replace(/<\/context\s*>/gi,``).trim(),is_user:i===`user_input`,context_name:i,from:a}}function ft(e){let t=typeof e==`string`?e:String(e||``),n=t.trim(),r=/^```[^\n]*\n([\s\S]*?)\n?```$/.exec(n);return r?r[1]:t}function pt(e){return ft(e).replace(/\n{3,}/g,`

`).trimEnd()}function mt(e){let t=String(e||``).toLowerCase();return t===`read`||t===`delete`||t===`move`?`read`:t===`edit`?`edit`:t===`execute`?`execute`:t===`search`?`search`:t===`think`?`think`:t===`fetch`?`fetch`:`other`}function ht(e){let t={read:`Reading files`,edit:`Editing files`,execute:`Running command`,search:`Searching`,think:`Thinking`,fetch:`Fetching`,other:`Tool call`};return t[e]||t.other}function gt(e){return e===`in_progress`?`In progress`:e===`completed`?`Completed`:e===`failed`?`Failed`:`Pending`}function _t(e){let t=String(e||``);return t.startsWith(`allow`)?`perm-option--allow`:t.startsWith(`reject`)?`perm-option--reject`:``}function vt(e){let t=String(e||``).split(/[\\/]/);return t[t.length-1]||String(e||``)}function yt(e){return e?typeof e.line==`number`?e.line:e.line&&typeof e.line.start==`number`?e.line.start:null:null}function bt(e){if(!e||!e.path)return``;let t=yt(e);return t?`${vt(e.path)}:${t}`:vt(e.path)}var xt=0;function R(e,t,n=`info`){let r=typeof t==`string`?t:String(t),i=`[${new Date().toLocaleTimeString([],{hour12:!1})}] ${String(n||`info`).padEnd(5)} ${r}`;e.update(e=>{let t=[...e.logs,i];return{...e,logs:t.length>200?t.slice(-200):t}})}function z(e,t,n=`info`){xt+=1;let r=xt;e.update(e=>({...e,toasts:[...e.toasts,{id:r,message:String(t),kind:n||`info`,visible:!1}]})),requestAnimationFrame(()=>{e.update(e=>({...e,toasts:e.toasts.map(e=>e.id===r?{...e,visible:!0}:e)}))}),setTimeout(()=>{e.update(e=>({...e,toasts:e.toasts.map(e=>e.id===r?{...e,visible:!1}:e)})),setTimeout(()=>{e.update(e=>({...e,toasts:e.toasts.filter(e=>e.id!==r)}))},260)},Ze)}function St(e,t,n=null){return K(e,n,[...Bt(G(e,n)),{id:W(`user`),type:`user`,text:t}],null)}function Ct(e,t,n=null,r=`Agent message`,i=``){return K(e,n,[...Bt(G(e,n)),{id:W(`context`),type:`context`,text:t,title:r,source:i}],null)}function wt(e,t=null){let n=B(e,t);return K(n,t,G(n,t).transcript,null,{turn_sequence:n.turn_sequence+1})}function Tt(e,t,n=null){if(!t)return e;let r=V(e,n),i=r?.parts[r.parts.length-1];if(r&&i&&i.type===`text`)return H(e,{...r,had_text:!0,parts:r.parts.map(e=>e.id===i.id?{...e,text:e.text+t,streaming:!0}:e)},n);let a=r&&i&&i.type===`thought`?{state:e,assistant:r}:zt(e,n),o=Ht({...a.assistant,had_text:!0,parts:[...U(a.assistant.parts),{id:W(`text`),type:`text`,text:t,streaming:!0}]});return H(a.state,o,n)}function Et(e,t,n=null){if(!t)return e;let r=V(e,n),i=r?.parts[r.parts.length-1],a=!!(r&&i&&i.type===`thought`),o=a?{state:e,assistant:r}:zt(e,n),s=a?{...o.assistant,parts:o.assistant.parts.map(e=>e.id===i.id?{...e,text:e.text+t}:e)}:{...o.assistant,parts:[...o.assistant.parts,{id:W(`thought`),type:`thought`,text:t,open:!1,auto_open:!1}]};return H(o.state,s,n)}function Dt(e,t,n,r=null){let i=String(t?.toolCallId);if(!n){let n=Vt(e,r,i);if(n)return H(e,{...n.assistant,parts:n.assistant.parts.map(e=>e.id===n.part.id?Wt(e,t):e)},r)}let a=Rt(e,r),o=a.assistant.parts.find(e=>e.type===`tool`&&e.tool_id===i);if(o)return H(a.state,{...a.assistant,parts:a.assistant.parts.map(e=>e.id===o.id?Wt(e,t):e)},r);let s=n?U(a.assistant.parts):a.assistant.parts,c=Wt(Ut(i),t);return H(a.state,{...a.assistant,parts:[...s,c]},r)}function Ot(e,t,n=null){let r=String(t?.toolCallId),i=L(t?.content),a=Vt(e,n,r);if(a)return H(e,{...a.assistant,parts:a.assistant.parts.map(e=>e.id===a.part.id?{...e,content_text:e.content_text+i}:e)},n);let o=Rt(e,n),s={...Ut(r),content_text:i};return H(o.state,{...o.assistant,parts:[...o.assistant.parts,s]},n)}function kt(e,t,n=null){let r=Rt(e,n),i=Array.isArray(t)?t.map(e=>({content:e?.content||``,status:e?.status||`pending`})):[],a=r.assistant.parts.find(e=>e.type===`plan`);return a?H(r.state,{...r.assistant,parts:r.assistant.parts.map(e=>e.id===a.id?{...e,entries:i}:e)},n):H(r.state,{...r.assistant,parts:[...U(r.assistant.parts),{id:W(`plan`),type:`plan`,entries:i}]},n)}function At(e,t,n,r=null){let i=V(e,r);if(!i)return e;let a=i.parts.find(e=>e.id===t);return!a||a.open===n?e:H(e,{...i,parts:i.parts.map(e=>e.id===t?{...e,open:n}:e)},r)}function B(e,t=null){let n=V(e,t);if(!n)return e;let r=H(e,{...n,parts:U(n.parts)},t);return K(r,t,G(r,t).transcript,null)}function jt(e,t=!0){return{...e,transcript:[],subagent_transcripts:{},subagent_current_assistant_ids:{},active_agent_session_id:null,permissions:[],current_assistant_id:null,turn_sequence:0,auto_scroll:!0,usage:t?{used:0,size:0,cost:null}:e.usage}}function Mt(e,t){let n=t?.bridgeId||e.bridge_id||``,r=n?`${n}:${t?.requestId}`:String(t?.requestId);if(e.permissions.some(e=>e.key===r))return e;let i=t?.toolCall||{},a=L(i.content).trim();return{...e,permissions:[...e.permissions,{key:r,request_id:t?.requestId,tool_call:i,options:Array.isArray(t?.options)?t.options:[],detail:a,resolved:!1,resolving:!1,chosen:null,status_kind:``,status_text:``}]}}function Nt(e,t,n){let r=e.permissions.find(e=>e.key===t);return!r||r.resolving===n?e:{...e,permissions:e.permissions.map(e=>e.key===t?{...e,resolving:n}:e)}}function Pt(e,t,n){let r=e.permissions.find(e=>e.key===t);if(!r||r.resolved)return e;let i=n==null?null:String(n),a=r.options.find(e=>String(e.optionId)===i)||null;return{...e,permissions:e.permissions.map(e=>e.key===t?{...e,resolved:!0,resolving:!1,chosen:i,status_kind:a?String(a.kind||``):`dismissed`,status_text:i===null?`Dismissed`:a?a.name:`Selected`}:e)}}function Ft(e,t){return e.permissions.some(e=>e.key===t)?{...e,permissions:e.permissions.filter(e=>e.key!==t)}:e}function It(e){return e.permissions.length?{...e,permissions:[]}:e}function Lt(e){return e.permissions.some(e=>!e.resolved)}function Rt(e,t=null){let n=V(e,t);if(n)return{state:e,assistant:n};let r=G(e,t),i={id:W(`turn`),type:`assistant`,turn:e.turn_sequence,parts:[],had_text:!1};return{state:K(e,t,[...r.transcript,i],i.id),assistant:i}}function V(e,t=null){let n=G(e,t);return n.current_id&&n.transcript.find(e=>e.id===n.current_id)||null}function zt(e,t=null){let n=G(e,t),r={id:W(`turn`),type:`assistant`,turn:e.turn_sequence,parts:[],had_text:!1};return{state:K(e,t,[...Bt(n),r],r.id),assistant:r}}function Bt(e){return e.current_id?e.transcript.map(t=>t.id===e.current_id&&t.type===`assistant`?{...t,parts:U(t.parts)}:t):e.transcript}function H(e,t,n=null){let r=G(e,n);return K(e,n,r.transcript.map(e=>e.id===t.id?t:e),r.current_id)}function Vt(e,t,n){let r=G(e,t);for(let e=r.transcript.length-1;e>=0;--e){let t=r.transcript[e];if(t.type!==`assistant`)continue;let i=t.parts.find(e=>e.type===`tool`&&e.tool_id===n);if(i)return{assistant:t,part:i}}return null}function Ht(e){let t=e.parts.find(e=>e.type===`thought`);if(!t)return e;let n=t.auto_open&&t.open?!1:t.open;return{...e,parts:e.parts.map(e=>e.id===t.id?{...e,open:n,auto_open:!1}:e)}}function U(e){return e.map(e=>e.type===`text`&&e.streaming?{...e,streaming:!1}:e)}function Ut(e){return{id:W(`tool`),type:`tool`,tool_id:e,kind:`other`,title:`Tool call`,status:`pending`,locations:[],content_text:``}}function Wt(e,t){let n={...e};if(t.kind&&(n.kind=mt(t.kind)),t.title?n.title=t.title:n.title&&n.title!==`Tool call`||(n.title=ht(n.kind)),t.status&&(n.status=t.status),Array.isArray(t.locations)&&(n.locations=t.locations),t.content!==void 0){let e=L(t.content);e&&(n.content_text=e)}return n}function W(e){return`${e}-${globalThis.crypto?.randomUUID?.()||`${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`}function G(e,t){return t?{transcript:e.subagent_transcripts?.[t]||[],current_id:e.subagent_current_assistant_ids?.[t]||null}:{transcript:e.transcript,current_id:e.current_assistant_id}}function K(e,t,n,r,i={}){return t?{...e,...i,subagent_transcripts:{...e.subagent_transcripts||{},[t]:n},subagent_current_assistant_ids:{...e.subagent_current_assistant_ids||{},[t]:r}}:{...e,...i,transcript:n,current_assistant_id:r}}function Gt(e,t,n={}){if(t&&typeof t==`object`)switch(t.type){case`status`:qt(e,t);break;case`session`:Jt(e,t);break;case`update`:if(!gn(e,t))break;Yt(e,t.update||{},t.sessionId,t.bridgeId);break;case`permission`:if(!_n(e,t))break;e.update(e=>Kt(e,t));break;case`permission_resolved`:Qt(e,t,n);break;case`prompt_done`:Zt(e,t,n);break;case`log`:R(e,t.message,t.level||`info`);break;case`details`:$t(e,t);break;case`subagents`:dn(e,t);break;case`error`:en(e,t)}}function Kt(e,t){let n=Mt(e,t);return n===e?e:{...n,busy:!0,turn_state:`requires_action`,busy_message:`Waiting for your approval`}}function qt(e,t){e.patch_session&&e.patch_session({status:t.status,activity:t.activity,activityDetail:t.detail}),t.agent&&e.update(e=>rn(e,t.agent)),t.detail&&R(e,String(t.detail),`info`),t.status===`exited`&&(e.update(e=>({...It(B(e)),busy:!1,stopping:!1,busy_message:``,turn_state:`idle`,retry_available:!!e.last_prompt})),z(e,`cecli exited`,`error`)),nn(e,t.status)}function Jt(e,t){tn(e,t.sessionId),t.modes&&e.update(e=>({...e,modes:t.modes})),Array.isArray(t.configOptions)&&sn(e,t.configOptions)}function Yt(e,t,n=null,r=null){if(!t||typeof t!=`object`)return;if(ut(t)===`subagent_update`){un(e,t,r);return}let i=ln(e.state,n);if(ut(t)===`session_message`){let r=t.recipientSessionId||n,i=t.userMessage?r:n;pn(e,t,ln(e.state,i))}else switch(ut(t)){case`agent_message_chunk`:e.update(e=>Tt(e,L(t.content),i));break;case`agent_thought_chunk`:e.update(e=>Et(e,L(t.content),i));break;case`tool_call`:e.update(e=>Dt(e,t,!0,i));break;case`tool_call_update`:e.update(e=>Dt(e,t,!1,i));break;case`tool_call_content_chunk`:e.update(e=>Ot(e,t,i));break;case`plan`:e.update(e=>kt(e,t.entries,i));break;case`usage_update`:e.update(e=>on(e,t));break;case`config_option_update`:sn(e,t.configOptions);break;case`current_mode_update`:e.update(e=>cn(e,t.currentModeId));break;case`state_update`:Xt(e,t,i)}}function Xt(e,t,n=null){let r=t.state;n?(e.update(e=>fn(e,n,r)),r===`idle`&&e.update(e=>B(e,n))):r===`requires_action`?e.update(e=>({...e,activity:`requires_action`,busy:!0,turn_state:`requires_action`,busy_message:`Waiting for your approval`})):r===`running`?e.update(e=>({...e,activity:`running`,busy:!0,turn_state:`running`,busy_message:`cecli is working…`})):r===`idle`&&e.update(e=>({...B(e),activity:`idle`,busy:!1,stopping:!1,turn_state:`idle`,busy_message:``}))}function Zt(e,t,n){e.update(e=>({...It(B(e)),activity:`idle`,busy:!1,stopping:!1,turn_state:`idle`,busy_message:``,retry_available:t&&t.stopReason===`cancelled`?!!e.last_prompt:e.retry_available})),t&&t.stopReason===`cancelled`&&R(e,`turn cancelled`,`info`),typeof n.on_prompt_done==`function`&&n.on_prompt_done()}function Qt(e,t,n){let r=t.bridgeId||e.state.bridge_id||``,i=r?`${r}:${t.requestId}`:String(t.requestId);e.update(e=>vn(Pt(e,i,t.optionId))),typeof n.on_permission_resolved==`function`&&n.on_permission_resolved(i)}function $t(e,t){let n=t.details||{};Array.isArray(t.subagents)&&dn(e,t),e.update(e=>({...e,skills:Array.isArray(n.skills)?n.skills:e.skills,mcp_servers:Array.isArray(n.mcpServers)?n.mcpServers:e.mcp_servers,workflows:Array.isArray(n.workflows)?n.workflows:e.workflows,context_files:Array.isArray(n.contextFiles)?n.contextFiles:e.context_files}))}function en(e,t){let n=t.message||`Unknown bridge error`;e.update(e=>({...e,retry_available:!!e.last_prompt})),R(e,n,`error`),z(e,n,`error`)}function tn(e,t){if(!t)return;let n=!1;e.update(e=>e.session_id&&e.session_id!==t?(n=!0,{...jt(e,!1),session_id:t}):e.session_id===t?e:{...e,session_id:t}),n&&z(e,`Session restarted`,`info`)}function nn(e,t){e.update(e=>{let n=t||e.status,r=n===`exited`;return e.status===n&&(!r||!e.busy)?e:{...e,status:n,busy:!r&&e.busy,stopping:!r&&e.stopping,busy_message:r?``:e.busy_message}})}function rn(e,t){if(!t)return e;let n=t.name||e.agent.name,r=t.version||``;return e.agent.name===n&&e.agent.version===r?e:{...e,agent:{name:n,version:r}}}function an(e,t){return typeof t!=`string`||!t||e.workspace===t?e:{...e,workspace:t}}function on(e,t){let n=Number(t.used),r=Number(t.size),i={...e.usage};return Number.isFinite(n)&&(i.used=n),Number.isFinite(r)&&(i.size=r),t.cost&&(i.cost=t.cost),i.used===e.usage.used&&i.size===e.usage.size&&i.cost===e.usage.cost?e:{...e,usage:i}}function sn(e,t){Array.isArray(t)&&e.update(e=>e.config_options===t?e:{...e,config_options:t})}function cn(e,t){if(t==null)return e;let n=String(t),r=!1,i=e.config_options.map(e=>e.id!==`mode`||String(e.currentValue)===n?e:(r=!0,{...e,currentValue:t}));return r?{...e,config_options:i}:e}function ln(e,t){return!t||e.session_id&&t===e.session_id?null:(e.subagents||[]).some(e=>e.sessionId===t)?t:null}function un(e,t,n=null){let r=t.sessionId;r&&(e.update(e=>{let n=e.subagents||[],i=n.find(e=>e.sessionId===r)||{sessionId:r};if(t.capabilities===null)return{...e,active_agent_session_id:e.active_agent_session_id===r?null:e.active_agent_session_id,subagents:n.map(e=>e.sessionId===r?{...e,removed:!0,running:!1,state:`idle`}:e)};let a={...i,removed:!1};t.title&&(a.title=t.title),t.description&&(a.description=t.description),t.capabilities&&(a.announced=!0),t.state&&typeof t.state==`object`&&(a.state=t.state.state||`idle`,a.running=a.state===`running`,t.state.stopReason&&(a.stopReason=t.state.stopReason),t.state.error&&(a.error=t.state.error));let o=n.some(e=>e.sessionId===r)?n.map(e=>e.sessionId===r?a:e):[...n,a];return{...e,subagents:o,subagent_transcripts:e.subagent_transcripts[r]?e.subagent_transcripts:{...e.subagent_transcripts,[r]:[]}}}),n&&e.patch_session&&e.patch_session(n,{subagents:e.state.subagents}))}function dn(e,t){let n=Array.isArray(t.subagents)?t.subagents:[];e.update(e=>{let t=new Map((e.subagents||[]).map(e=>[e.sessionId,e]));for(let e of n)e?.sessionId&&t.set(e.sessionId,{...t.get(e.sessionId),...e,removed:!1});let r={...e.subagent_transcripts};for(let e of n)e?.sessionId&&!r[e.sessionId]&&(r[e.sessionId]=[]);let i=e.active_agent_session_id&&t.has(e.active_agent_session_id)?e.active_agent_session_id:null;return{...e,active_agent_session_id:i,subagents:[...t.values()],subagent_transcripts:r}}),t.bridgeId&&e.patch_session&&e.patch_session(t.bridgeId,{subagents:n})}function fn(e,t,n){return{...e,subagents:(e.subagents||[]).map(e=>e.sessionId===t?{...e,state:n,running:n===`running`}:e)}}function pn(e,t,n){let r=dt(L(t.content));if(!r.text)return;let i=!!t.userMessage||r.is_user,a=mn(r.context_name);e.update(e=>i?St(e,r.text,n):Ct(e,r.text,n,a,hn(e,t.senderSessionId)||r.from))}function mn(e){let t=String(e||``).trim();if(!t)return`Agent message`;let n=t.replace(/[_-]+/g,` `).trim();return n.charAt(0).toUpperCase()+n.slice(1)}function hn(e,t){if(!t)return``;if(e.session_id&&t===e.session_id)return`Main`;let n=(e.subagents||[]).find(e=>e.sessionId===t);return n?.title||n?.name||String(t)}function gn(e,t){if(!t||!t.update)return!1;if(!t.sessionId)return!0;let n=e.state;return n.session_id?t.sessionId===n.session_id||n.subagents.some(e=>e.sessionId===t.sessionId):!1}function _n(e,t){if(!t||t.requestId===void 0)return!1;if(!t.sessionId)return!0;let n=e.state;return!n.session_id||t.sessionId===n.session_id||n.subagents.some(e=>e.sessionId===t.sessionId)}function vn(e){if(Lt(e))return e;let t=e.busy?`running`:`idle`,n=e.busy?`cecli is working…`:``;return e.turn_state===t&&e.busy_message===n?e:{...e,turn_state:t,busy_message:n}}function yn(e,t,n=null){if(!t||typeof t!=`object`)return;let r=n||e.active_bridge_id;r&&e.update_for(r,e=>{let n=e,r=Array.isArray(t.messages)?t.messages:[];r.length&&!bn(n.transcript)&&(n={...n,transcript:[...xn(r,`main`),...n.transcript],current_assistant_id:null});let i=Array.isArray(t.subagents)?t.subagents:[];if(!i.length)return n;let a=n.subagent_transcripts||{},o=n.subagent_current_assistant_ids||{},s=!1;for(let e of i){let t=e?.sessionId,n=Array.isArray(e?.messages)?e.messages:[];if(!t||!n.length)continue;let r=a[t]||[];bn(r)||(a={...a,[t]:[...xn(n,t),...r]},o={...o,[t]:null},s=!0)}return s?{...n,subagent_transcripts:a,subagent_current_assistant_ids:o}:n})}function bn(e){return(e||[]).some(e=>e&&(e.type===`user`||e.type===`assistant`))}function xn(e,t){let n=[],r=new Map,i=0;return e.forEach((e,a)=>{let o=String(e?.role||``),s=dt(e?.content).text;if(o===`user`)s&&n.push({id:`${t}-user-${a}`,type:`user`,text:s});else if(o===`assistant`){let o=[],c=dt(e?.reasoning).text;c&&o.push({id:`${t}-thought-${a}`,type:`thought`,text:c,open:!1,auto_open:!1}),s&&o.push({id:`${t}-text-${a}`,type:`text`,text:s,streaming:!1});let l=Array.isArray(e?.toolCalls)?e.toolCalls:[];for(let[e,n]of l.entries()){let i=Sn(`${t}-tool-${a}-${e}`,n);r.set(String(i.tool_id),i),o.push(i)}if(!o.length)return;n.push({id:`${t}-turn-${a}`,type:`assistant`,turn:i++,parts:o,had_text:!!s})}else if(o===`tool`){let o=r.get(String(e?.toolCallId||``));if(o){s&&(o.content_text=o.content_text?`${o.content_text}\n${s}`:s);return}if(!s)return;n.push({id:`${t}-tool-turn-${a}`,type:`assistant`,turn:i++,parts:[{id:`${t}-tool-out-${a}`,type:`tool`,tool_id:String(e?.toolCallId||`tool-${a}`),kind:`other`,title:`Tool result`,status:`completed`,locations:[],content_text:s}],had_text:!1})}}),n}function Sn(e,t){let n=typeof t?.arguments==`string`?t.arguments:JSON.stringify(t?.arguments??``);return{id:e,type:`tool`,tool_id:String(t?.id||e),kind:`other`,title:String(t?.name||`Tool call`),status:`completed`,locations:[],content_text:n}}function Cn(e,t,n=null,r=null){if(!t||typeof t!=`object`)return;let i=n||t.bridgeId||e.active_bridge_id||``;Array.isArray(t.sessions)&&e.set_sessions(t.sessions,t.maxSessions),!e.active_bridge_id&&i&&e.set_active(i);let a=e.scoped(i);if(a.update(e=>an(e,t.workspace)),a.update(e=>({...e,bridge_id:i})),t.sessionId!==void 0&&a.update(e=>({...e,session_id:t.sessionId})),t.title&&a.update(e=>({...e,title:t.title})),t.agent&&a.update(e=>rn(e,t.agent)),t.modes&&a.update(e=>({...e,modes:t.modes})),Array.isArray(t.configOptions)&&sn(a,t.configOptions),a.update(e=>({...e,activity:t.activity||e.activity,activity_detail:t.activityDetail||``,subagents:Array.isArray(t.subagents)?t.subagents:e.subagents,skills:Array.isArray(t.skills)?t.skills:e.skills,mcp_servers:Array.isArray(t.mcpServers)?t.mcpServers:e.mcp_servers,workflows:Array.isArray(t.workflows)?t.workflows:e.workflows,context_files:Array.isArray(t.contextFiles)?t.contextFiles:e.context_files,details_supported:t.detailsSupported===void 0?e.details_supported:t.detailsSupported})),typeof t.busy==`boolean`&&a.update(e=>{if(t.busy){let t=Lt(e);return{...e,busy:!0,stopping:e.stopping,turn_state:t?`requires_action`:`running`,busy_message:e.stopping?`Stopping…`:t?`Waiting for your approval`:`cecli is working…`}}return{...e,busy:!1,stopping:!1,turn_state:`idle`,busy_message:``}}),t.usage&&a.update(e=>on(e,t.usage)),Array.isArray(t.permissions)){let e=t.permissions;a.update(t=>{let n=new Set(e.map(e=>e.bridgeId||i?`${e.bridgeId||i}:${e.requestId}`:String(e.requestId))),a=t.permissions.filter(e=>r===null?n.has(e.key):!r.has(e.key)||n.has(e.key));return a.length===t.permissions.length?t:{...t,permissions:a}});for(let t of e)a.update(e=>Mt(e,{...t,bridgeId:i}))}nn(a,t.status),a.update(e=>e.stopping?e:vn(e))}function q(){return{status:`starting`,busy:!1,busy_message:``,connected:!1,had_connection:!1,disconnect_notified:!1,stopping:!1,workspace:``,bridge_id:null,title:``,sessions:[],active_bridge_id:null,max_sessions:8,activity:`idle`,activity_detail:``,subagents:[],subagent_transcripts:{},subagent_current_assistant_ids:{},active_agent_session_id:null,skills:[],mcp_servers:[],workflows:[],context_files:[],details_supported:null,session_id:null,config_options:[],modes:{},agent:{name:`cecli`,version:``},turn_state:`idle`,usage:{used:0,size:0,cost:null},auto_scroll:!0,last_prompt:``,retry_available:!1,draft:``,draft_revision:0,transcript:[],available_commands:[],permissions:[],logs:[],toasts:[],turn_sequence:0,current_assistant_id:null,new_chat_pending:!1,restart_pending:!1,sidebar_open:!0}}var wn=class{constructor(e){this._views=new Map([[``,this._strip(e)]]),this._active_bridge_id=null,this._sessions=[],this._max_sessions=e.max_sessions||8,this._revisions=new Map,this._listeners=new Set}get state(){return this._project(this._active_bridge_id||``)}get active_bridge_id(){return this._active_bridge_id}get sessions(){return this._sessions}revision(e){return this._revisions.get(e||``)||0}subscribe(e){return this._listeners.add(e),()=>this._listeners.delete(e)}update(e){this._write(this._active_bridge_id||``,e)}update_for(e,t){let n=e||this._active_bridge_id||``;this._write(n,t)}scoped(e){let t=this;return{bridge_id:e,get state(){return t.state_for(e)},update:n=>t.update_for(e,n),patch_session:(n,r)=>r===void 0?t.patch_session(e,n):t.patch_session(n,r)}}state_for(e){let t=e||``;return!this._active_bridge_id||t===this._active_bridge_id?this.state:this._project(t)}set_active(e){let t=e||null;if(t===this._active_bridge_id)return;let n=this.state;if(this._views.set(this._active_bridge_id||``,this._strip(n)),this._active_bridge_id=t,t&&!this._views.has(t)){let e=this._sessions.find(e=>e.bridgeId===t),r=q();r.connected=n.connected,r.had_connection=n.had_connection,r.disconnect_notified=n.disconnect_notified,r.bridge_id=t,r.title=e?.title||``,r.workspace=e?.workspace||``,r.status=e?.status||`starting`,r.session_id=e?.sessionId||null,r.busy=!!e?.busy,r.activity=e?.activity||`idle`,r.activity_detail=e?.activityDetail||``,this._views.set(t,this._strip(r))}this.emit()}set_sessions(e,t){Array.isArray(e)&&(this._sessions=[...e]),Number.isFinite(t)&&(this._max_sessions=t),!this._active_bridge_id&&this._sessions.length?this.set_active(this._sessions[0].bridgeId):this.emit()}remove_session(e){this._views.delete(e),this._sessions=this._sessions.filter(t=>t.bridgeId!==e),this._active_bridge_id===e&&(this._active_bridge_id=this._sessions[0]?.bridgeId||null),this.emit()}patch_session(e,t){if(typeof e==`object`&&e&&t===void 0&&(t=e,e=this._active_bridge_id),!e||!t)return;let n=!1,r=Object.fromEntries(Object.entries(t).filter(([,e])=>e!==void 0));this._sessions=this._sessions.map(t=>t.bridgeId===e?(n=!0,{...t,...r}):t),n&&this.emit()}emit(){this._emit_scheduled||(this._emit_scheduled=!0,queueMicrotask(()=>{this._emit_scheduled=!1;for(let e of this._listeners)e(this.state)}))}_project(e){let t=this._views.get(e);return t||=e?q():this._views.get(``)||q(),{...t,sessions:this._sessions,active_bridge_id:this._active_bridge_id,max_sessions:this._max_sessions}}_write(e,t){let n=this._views.get(e)||q(),r=t(this._project(e));if(!r)return;let i=this._strip(r);this._same_view(n,i)||(this._views.set(e,i),this._revisions.set(e,this.revision(e)+1),this.emit())}_same_view(e,t){let n=Object.keys(e);return n.length===Object.keys(t).length&&n.every(n=>e[n]===t[n])}_strip(e){let t={...e};return delete t.sessions,delete t.active_bridge_id,delete t.max_sessions,t}},J=class{constructor(e,t){this.host=e,this.store=t,this._unsubscribe=null,e.addController(this)}get state(){return this.store.state}hostConnected(){this._unsubscribe=this.store.subscribe(()=>this.host.requestUpdate())}hostDisconnected(){this._unsubscribe&&this._unsubscribe(),this._unsubscribe=null}},Y={connection_label(e){let t=e.status||`starting`;return t===`ready`&&e.busy&&(t=`busy`),!e.connected&&e.had_connection&&(t=`reconnecting`),t},turn_label(e){return(e.turn_state||`idle`).replace(/_/g,` `)},busy_text(e){return e.busy_message||`cecli is working…`},retry_visible(e){return!(!e.retry_available||!e.last_prompt||e.busy||e.stopping)},usage_percent(e){let{used:t,size:n}=e.usage;return n>0?Math.min(Math.max(t/n*100,0),100):0},usage_level(e){let t=Y.usage_percent(e);return t>90?`high`:t>70?`warn`:`normal`},active_agent(e){return e.active_agent_session_id&&(e.subagents||[]).find(t=>t.sessionId===e.active_agent_session_id)||null},visible_transcript(e){return e.active_agent_session_id?e.subagent_transcripts?.[e.active_agent_session_id]||[]:e.transcript},visible_busy(e){return e.active_agent_session_id?!!Y.active_agent(e)?.running:e.busy},has_transcript(e){return Y.visible_transcript(e).length>0}},X=new wn(q()),Z=new class{constructor(){this.socket=null,this.pending=new Map,this.sequence=0,this.open_promise=null}get ready(){return this.socket?.readyState===WebSocket.OPEN}async connect(){return this.ready?!0:(this.open_promise||=new Promise(e=>{let t=window.__CECLI_TOKEN__||``,n=[`cecli.desktop.v1`];t&&n.push(`token.${t}`);let r=window.location.protocol===`https:`?`wss`:`ws`,i;try{i=new WebSocket(`${r}://${window.location.host}/ws`,n)}catch{this.open_promise=null,e(!1);return}this.socket=i,i.onopen=()=>{this.open_promise=null,e(!0)},i.onmessage=e=>this._receive(e.data),i.onclose=()=>{this.socket=null,this.open_promise=null,this._reject_pending(`WebSocket closed`)},i.onerror=()=>{this.open_promise=null,this._reject_pending(`WebSocket error`),e(!1)}}),this.open_promise)}async request(e,t={}){if(!this.ready&&!await this.connect())throw Error(`WebSocket is unavailable`);this.sequence+=1;let n=`c${this.sequence}`;return new Promise((r,i)=>{this.pending.set(n,{resolve:r,reject:i});try{this.socket.send(JSON.stringify({id:n,command:e,params:t}))}catch(e){this.pending.delete(n),i(e)}})}_receive(e){let t;try{t=JSON.parse(e)}catch{return}if(!t||t.id===void 0)return;let n=this.pending.get(t.id);n&&(this.pending.delete(t.id),t.ok?n.resolve(t.result):n.reject(Error(t.error||`WebSocket command failed`)))}_reject_pending(e){for(let t of this.pending.values())t.reject(Error(e));this.pending.clear()}},Q=new class{constructor(e){this.store=e,this.event_source=null,this.state_generations=new Map,this.permission_timers=new Map,this.history_loaded=new Set,this.reconnect_timer=null,this.reconnect_delay=Ye}start(){this.connect(),this.sync_timer=setInterval(()=>this.sync_now(),5e3)}sync_now(){this.store.state.connected&&(this.refresh_sessions(),this.store.state.busy||this.refresh_state(this.store.active_bridge_id),this.hydrate_history(this.store.active_bridge_id))}connect(){clearTimeout(this.reconnect_timer),this.reconnect_timer=null,this.event_source&&this.event_source.close();let e=new EventSource(`/api/events`);this.event_source=e,e.onopen=()=>{this.reconnect_delay=Ye,this.store.update(e=>({...e,connected:!0,had_connection:!0,disconnect_notified:!1})),this.refresh_sessions(),this.refresh_state(this.store.active_bridge_id)},e.onmessage=e=>{let t;try{t=JSON.parse(e.data)}catch{R(this.store,`malformed event: ${e.data}`,`error`);return}if(t.type===`sessions`){this.store.set_sessions(t.sessions,t.maxSessions),this._sync_active_summary();return}let n=t.bridgeId||this.store.active_bridge_id,r=n?this.store.scoped(n):this.store;if(Gt(r,t,{on_permission_resolved:e=>this.schedule_permission_cleanup(e,n),on_prompt_done:()=>this.clear_permission_cleanup(n)}),this._track_session_event(r,t),t.type===`status`&&t.status===`ready`&&this.hydrate_history(n),t.type===`subagents`&&this.hydrate_history(n),t.type===`session`&&n){for(let e of this.history_loaded)e.startsWith(`${n}:`)&&this.history_loaded.delete(e);this.hydrate_history(n)}},e.onerror=()=>{this.event_source===e&&(e.close(),this.event_source=null,this.store.update(e=>({...e,connected:!1})),this.store.state.had_connection&&!this.store.state.disconnect_notified&&(this.store.update(e=>({...e,disconnect_notified:!0})),z(this.store,`Connection lost — reconnecting…`,`error`)),this.schedule_reconnect())}}schedule_reconnect(){if(this.reconnect_timer)return;let e=this.reconnect_delay;this.reconnect_timer=setTimeout(()=>{this.reconnect_timer=null,this.reconnect_delay=Math.min(this.reconnect_delay*2,Xe),this.connect()},e)}async refresh_sessions(){try{let e=await Ke();this.store.set_sessions(e.sessions,e.maxSessions),this._sync_active_summary()}catch(e){R(this.store,`session list failed: ${e.message}`,`error`)}}_sync_active_summary(){let e=this.store.active_bridge_id;if(!e)return;let t=this.store.sessions.find(t=>t.bridgeId===e);t&&this.store.update_for(e,e=>{let n=Array.isArray(t.subagents)?t.subagents:e.subagents,r={...e.subagent_transcripts};for(let e of n)e?.sessionId&&!r[e.sessionId]&&(r[e.sessionId]=[]);return{...e,subagents:n,subagent_transcripts:r,skills:Array.isArray(t.skills)?t.skills:e.skills,mcp_servers:Array.isArray(t.mcpServers)?t.mcpServers:e.mcp_servers,workflows:Array.isArray(t.workflows)?t.workflows:e.workflows,context_files:Array.isArray(t.contextFiles)?t.contextFiles:e.context_files}})}async refresh_state(e=this.store.active_bridge_id,t=0){if(!e&&(await this.refresh_sessions(),e=this.store.active_bridge_id,!e))return;let n=(this.state_generations.get(e)||0)+1;this.state_generations.set(e,n);let r=this.store.revision(e),i=new Set(this.store.state_for(e).permissions.map(e=>e.key));try{let a=await Ge(e);if(this.state_generations.get(e)!==n)return;if(this.store.revision(e)!==r&&this.store.state_for(e).session_id&&t<1){await this.refresh_state(e,t+1);return}Cn(this.store,a,e,i),this.hydrate_history(e)}catch(e){R(this.store,`state sync failed: ${e.message}`,`error`)}}async hydrate_history(e=this.store.active_bridge_id){let t=e||this.store.active_bridge_id;if(!t)return;let n=this.store.state_for(t);if(n.status!==`ready`)return;let r=[`main`];for(let e of n.subagents||[])e?.sessionId&&!e.removed&&r.push(e.sessionId);let i=r.filter(e=>!bn(e===`main`?n.transcript:n.subagent_transcripts?.[e]||[])&&!this.history_loaded.has(`${t}:${e}`));if(!i.length)return;for(let e of i)this.history_loaded.add(`${t}:${e}`);let a=null;try{a=await Z.request(`history.get`,{bridgeId:t})}catch{try{a=await qe(t)}catch{for(let e of i)this.history_loaded.delete(`${t}:${e}`);return}}yn(this.store,a,t)}async switch_session(e){e&&(this.store.update(e=>({...e,active_agent_session_id:null})),e!==this.store.active_bridge_id&&(this.store.set_active(e),await this.refresh_state(e)))}async create_session(e=null,t=null){let n={...e?{cwd:e}:{},...t?{title:t}:{}},r=null;try{r=(await Z.request(`sessions.create`,n))?.bridgeId||null}catch{r=(await I(`/api/sessions`,n))?.bridgeId||null}return await this.refresh_sessions(),r&&await this.switch_session(r),r}async close_session(e){try{await Z.request(`sessions.close`,{bridgeId:e})}catch{await I(`/api/sessions/close`,{bridgeId:e})}this.store.remove_session(e),await this.refresh_sessions(),await this.refresh_state(this.store.active_bridge_id)}async select_agent(e,t=null){e&&e!==this.store.active_bridge_id&&await this.switch_session(e),this.store.update(e=>({...e,active_agent_session_id:t||null,auto_scroll:!0})),this.hydrate_history(e||this.store.active_bridge_id)}async message_subagent(e,t){let n=this.store.active_bridge_id;n&&(await I(`/api/subagent/message`,{bridgeId:n,sessionId:e,text:t}),this.store.update(t=>({...t,subagents:(t.subagents||[]).map(t=>t.sessionId===e?{...t,running:!0,state:`running`}:t)})))}async registry_action(e,t,n){let r=this.store.active_bridge_id;if(!r)return;let i=e===`workflows`&&t===`run`;try{let i={bridgeId:r,name:n};e===`context`&&(i.path=n),await Z.request(`${e}.${t}`,i)}catch{await I(`/api/${e}`,{bridgeId:r,action:t,name:n})}i&&this.store.update(e=>{let t=`/workflows run ${n}`;return{...wt(St(e,t)),active_agent_session_id:null,last_prompt:t,retry_available:!1,busy:!0,stopping:!1,busy_message:`cecli is working…`,turn_state:`running`}}),await this.refresh_state(r)}async complete(e){let t=this.store.active_bridge_id;try{return await Z.request(`complete.get`,{bridgeId:t,text:e})}catch{return Je(t,e)}}async send_prompt(e){let t=String(e||``).trim(),n=this.store.state,r=this.store.active_bridge_id,i=n.active_agent_session_id;if(!r&&n.sessions.length)return z(this.store,`No active session`,`error`),!1;if(!t)return!1;if(this.store.state.status!==`ready`)return z(this.store,`cecli is not ready yet`,`error`),!1;if(i)try{return await I(`/api/subagent/message`,{bridgeId:r,sessionId:i,text:t}),this.store.update(e=>({...e,subagents:(e.subagents||[]).map(e=>e.sessionId===i?{...e,running:!0,state:`running`}:e)})),!0}catch(e){return z(this.store,e.message,`error`),!1}if(this.store.state.busy)return!1;try{return await I(`/api/prompt`,r?{bridgeId:r,text:t}:{text:t}),this.store.update(e=>({...wt(St(e,t)),last_prompt:t,retry_available:!1,busy:!0,stopping:!1,busy_message:`cecli is working…`,turn_state:`running`})),!0}catch(e){return this.store.update(e=>({...e,last_prompt:t,retry_available:!0})),z(this.store,e.message,`error`),!1}}async cancel_turn(){let e=this.store.state,t=e.active_agent_session_id;if(t){if(!(e.subagents||[]).find(e=>e.sessionId===t)?.running)return;try{await I(`/api/subagent/cancel`,{bridgeId:this.store.active_bridge_id,sessionId:t})}catch(e){z(this.store,e.message,`error`)}}else if(e.busy&&!e.stopping){this.store.update(e=>({...e,stopping:!0,busy_message:`Stopping…`}));try{await I(`/api/cancel`,{bridgeId:this.store.active_bridge_id})}catch(e){this.store.update(e=>({...e,stopping:!1})),z(this.store,e.message,`error`)}}}async new_chat(){if(this.store.state.busy){z(this.store,`Finish or stop the current turn first`,`error`);return}this.clear_permission_cleanup(),this.history_loaded.clear(),this.store.update(e=>({...e,new_chat_pending:!0}));let e=this.store.state.workspace;try{await I(`/api/new_session`,{...this.store.active_bridge_id?{bridgeId:this.store.active_bridge_id}:{},...e?{cwd:e}:{}}),this.store.update(e=>({...jt(e),session_id:null,busy:!1,stopping:!1,busy_message:``,turn_state:`idle`})),z(this.store,`Started a new chat`,`info`),this.refresh_state()}catch(e){z(this.store,e.message,`error`)}finally{this.store.update(e=>({...e,new_chat_pending:!1}))}}async restart_server(){this.clear_permission_cleanup(),this.history_loaded.clear(),this.store.update(e=>({...e,restart_pending:!0}));try{await I(`/api/restart`,{bridgeId:this.store.active_bridge_id}),this.store.update(e=>({...jt(e),session_id:null,busy:!1,stopping:!1,busy_message:``,status:`starting`,turn_state:`idle`})),z(this.store,`Restarting cecli…`,`info`)}catch(e){z(this.store,e.message,`error`)}finally{this.store.update(e=>({...e,restart_pending:!1}))}}async change_config(e,t){try{return await I(`/api/config`,{bridgeId:this.store.active_bridge_id,configId:e,value:t}),this.store.update(n=>({...n,config_options:n.config_options.map(n=>n.id===e?{...n,currentValue:t}:n)})),!0}catch(e){return z(this.store,e.message,`error`),!1}}async resolve_permission(e,t){let n=this.store.state,r=n.permissions.find(t=>String(t.request_id)===String(e));if(!r||r.resolving||r.resolved)return;let i=n.bridge_id||this.store.active_bridge_id,a=r.key;this.store.update(e=>Nt(e,a,!0));try{await I(`/api/permission`,{bridgeId:i,requestId:r.request_id,optionId:t}),this.store.update(e=>Pt(e,a,t)),this.store.update(e=>vn(e)),this.schedule_permission_cleanup(a,i)}catch(e){let t=this.store.state.permissions.find(e=>e.key===a);if(t&&t.resolved)return;this.store.update(e=>Nt(e,a,!1)),z(this.store,e.message,`error`)}}schedule_permission_cleanup(e,t=this.store.active_bridge_id){if(this.permission_timers.has(e))return;let n=setTimeout(()=>{this.permission_timers.delete(e),this.store.update_for(t,t=>Ft(t,e)),this.store.patch_session(t,{permissionCount:this.store.state_for(t).permissions.filter(e=>!e.resolved).length})},Qe);this.permission_timers.set(e,n)}clear_permission_cleanup(e=null){let t=e?`${e}:`:``;for(let[e,n]of this.permission_timers)(!t||e.startsWith(t))&&(clearTimeout(n),this.permission_timers.delete(e))}_track_session_event(e,t){if(e.patch_session){if(t.type===`update`){if(t.sessionId&&t.sessionId!==e.state.session_id)return;let n=t.update||{};n.sessionUpdate===`state_update`&&n.state?e.patch_session({activity:n.state,busy:n.state===`running`||n.state===`requires_action`}):n.sessionUpdate===`tool_call`&&n.title&&e.patch_session({activityDetail:n.title})}else t.type===`permission`||t.type===`permission_resolved`?e.patch_session({permissionCount:e.state.permissions.filter(e=>!e.resolved).length}):t.type===`prompt_done`&&e.patch_session({activity:`idle`,busy:!1,permissionCount:0})}}set_thought_open(e,t,n=null){this.store.update(r=>At(r,e,t,n))}set_auto_scroll(e){let t=!!e;this.store.update(e=>e.auto_scroll===t?e:{...e,auto_scroll:t})}jump_to_latest(){this.set_auto_scroll(!0)}fill_composer(e){this.store.update(t=>({...t,draft:String(e||``),draft_revision:t.draft_revision+1}))}}(X),Tn=class extends M{constructor(){super(),this._store=new J(this,X)}createRenderRoot(){return this}render(){let e=this._store.state,t=(e.subagents||[]).filter(e=>!e.removed);if(!t.length)return D;let n=e.active_agent_session_id;return T`
      <div class="agent-strip" role="tablist" aria-label="Agent transcripts">
        <button
          class="agent-pill"
          type="button"
          role="tab"
          data-active=${!n}
          aria-selected=${!n}
          @click=${()=>Q.select_agent(e.active_bridge_id,null)}
        >
          <span class="agent-dot" data-status=${e.busy?`running`:`idle`} aria-hidden="true"></span>
          <span class="agent-name">Main</span>
        </button>
        ${F(t,e=>e.sessionId,t=>T`
            <button
              class="agent-pill"
              type="button"
              role="tab"
              data-active=${n===t.sessionId}
              aria-selected=${n===t.sessionId}
              title=${t.description||t.title||t.name||t.sessionId}
              @click=${()=>Q.select_agent(e.active_bridge_id,t.sessionId)}
            >
              <span
                class="agent-dot"
                data-status=${t.running?`running`:t.state||`idle`}
                aria-hidden="true"
              ></span>
              <span class="agent-name">${t.title||t.name||t.sessionId}</span>
            </button>
          `)}
      </div>
    `}};customElements.define(`agent-strip`,Tn);var En=class extends M{constructor(){super(),this._store=new J(this,X)}createRenderRoot(){return this}render(){let e=this._store.state,t=Y.connection_label(e);return T`
      <header class="topbar">
        <div class="brand">
          <img class="brand-mark" src=${`/static/cecli-temp-logo-favicon.svg`} alt="" aria-hidden="true" />
          <span class="brand-name">cecli</span>
        </div>

        <div class="workspace" title=${e.workspace||``}>
          <span class="workspace-path">${e.workspace||`—`}</span>
        </div>

        <span
          class="connection-status"
          data-status=${t}
          role="status"
          aria-label=${`Connection status: ${t}`}
        >
          <span class="status-dot" aria-hidden="true"></span>
          <span class="status-label">${t}</span>
        </span>
      </header>
    `}};customElements.define(`app-header`,En);var Dn=class extends M{constructor(){super(),this._store=new J(this,X),this._has_text=!1,this._sending=!1,this._applied_revision=0,this._completions=[],this._completion_descriptions={},this._completion_index=0,this._completion_start=0,this._completion_seq=0,this._completion_timer=null,this._on_global_keydown=this._on_global_keydown.bind(this)}createRenderRoot(){return this}connectedCallback(){super.connectedCallback(),document.addEventListener(`keydown`,this._on_global_keydown)}disconnectedCallback(){document.removeEventListener(`keydown`,this._on_global_keydown),super.disconnectedCallback()}updated(){let e=this._store.state;if(e.draft_revision===this._applied_revision)return;this._applied_revision=e.draft_revision;let t=this._textarea();t&&(t.value=e.draft,this._has_text=e.draft.trim().length>0,this._auto_grow(),t.focus())}render(){let e=this._store.state,t=Y.active_agent(e),n=t?!!t.running:e.busy,r=Y.retry_visible(e),i=!n&&(this._sending||e.status!==`ready`||!this._has_text);return T`
      <footer class="composer">
        <div class="busy-indicator" ?hidden=${!n}>
          <span class="spinner" aria-hidden="true"></span>
          <span>${Y.busy_text(e)}</span>
        </div>
        ${this._render_completions()}
        <div class="composer-box">
          <textarea
            id="composer-input"
            rows="1"
            placeholder="Ask cecli anything…"
            aria-label="Message cecli"
            autocomplete="off"
            spellcheck="true"
            @input=${this._on_input}
            @keydown=${this._on_keydown}
          ></textarea>
          <button
            class="send-btn"
            type="button"
            data-mode=${n?`stop`:`send`}
            aria-label=${n?`Stop this turn`:`Send message`}
            ?disabled=${i}
            @click=${this._on_send_click}
          >${n?rt:nt}</button>
        </div>
        <div class="composer-meta">
          <span class="hint">Enter to send · Shift+Enter for newline · Esc to stop</span>
          <div class="composer-state">
            <button
              class="retry-btn"
              type="button"
              ?hidden=${!r}
              @click=${this._retry}
            >Retry last</button>
            <span class="turn-status" data-state=${e.turn_state}>
              <span class="turn-dot" aria-hidden="true"></span>
              <span>${Y.turn_label(e)}</span>
            </span>
          </div>
        </div>
      </footer>
    `}_textarea(){return this.querySelector(`#composer-input`)}_auto_grow(){let e=this._textarea();e&&(e.style.height=`auto`,e.style.height=`${Math.min(e.scrollHeight,180)}px`)}_on_input(){let e=this._textarea();e&&(this._has_text=e.value.trim().length>0,this._auto_grow(),this._schedule_completions(e.value),this.requestUpdate())}_on_keydown(e){if(this._completions.length){if(e.key===`ArrowDown`||e.key===`ArrowUp`){e.preventDefault();let t=e.key===`ArrowDown`?1:-1,n=this._completions.length;this._completion_index=(this._completion_index+t+n)%n,this.requestUpdate();return}if((e.key===`Tab`||e.key===`Enter`)&&!e.shiftKey&&!e.isComposing){e.preventDefault(),this._accept_completion();return}if(e.key===`Escape`){e.preventDefault(),e.stopPropagation(),this._dismiss_completions();return}}e.key!==`Enter`||e.shiftKey||e.isComposing||(e.preventDefault(),this._is_busy()||this._submit())}_on_send_click(){this._is_busy()?Q.cancel_turn():this._submit()}async _submit(){let e=this._textarea();if(!e||this._sending)return;let t=e.value.trim();if(!t||!X.state.active_agent_session_id&&X.state.busy)return;this._sending=!0,this.requestUpdate();let n=!1;try{n=await Q.send_prompt(t)}finally{this._sending=!1}n&&(e.value=``,this._has_text=!1,this._auto_grow(),this._dismiss_completions()),this.requestUpdate()}_retry(){let e=X.state;if(e.busy||!e.last_prompt)return;let t=this._textarea();t&&(t.value=e.last_prompt,this._has_text=!0,this._auto_grow(),this.requestUpdate(),this._submit())}_on_global_keydown(e){if(e.key!==`Escape`||!this._is_busy())return;let t=this._textarea();document.activeElement===t&&t.value.trim()||(e.preventDefault(),Q.cancel_turn())}_is_busy(){let e=X.state,t=e.active_agent_session_id;return t?!!(e.subagents||[]).find(e=>e.sessionId===t)?.running:!!e.busy}_render_completions(){return this._completions.length?T`
      <div class="completion-popover" role="listbox" aria-label="Completions">
        <ul class="completion-list">
          ${this._completions.map((e,t)=>T`
              <li>
                <button
                  type="button"
                  class="completion-item"
                  role="option"
                  data-active=${t===this._completion_index}
                  aria-selected=${t===this._completion_index}
                  @mousedown=${e=>e.preventDefault()}
                  @click=${()=>this._select_completion(t)}
                >
                  <span class="completion-label">${e}</span>
                  ${this._completion_descriptions[e]?T`<span class="completion-detail">
                        ${this._completion_descriptions[e]}
                      </span>`:D}
                </button>
              </li>
            `)}
        </ul>
      </div>
    `:D}_schedule_completions(e){if(clearTimeout(this._completion_timer),!e.trim()){this._dismiss_completions();return}let t=++this._completion_seq;this._completion_timer=setTimeout(async()=>{try{let n=await Q.complete(e);if(t!==this._completion_seq)return;let r=Array.isArray(n?.suggestions)?n.suggestions:[];this._completions=r,this._completion_descriptions=n?.descriptions||{},this._completion_start=Number.isFinite(n?.start)?n.start:e.length,this._completion_index=0,this.requestUpdate()}catch{t===this._completion_seq&&this._dismiss_completions()}},120)}_select_completion(e){this._completion_index=e,this._accept_completion()}_accept_completion(){let e=this._textarea();if(!e||!this._completions.length)return;let t=e.value,n=String(this._completions[this._completion_index]),r=Math.max(0,Math.min(this._completion_start,t.length)),i=n.startsWith(`/`)&&r===0?`${n} `:n;e.value=t.slice(0,r)+i;let a=e.value.length;e.setSelectionRange(a,a),this._has_text=e.value.trim().length>0,this._auto_grow(),this._dismiss_completions(),e.focus()}_dismiss_completions(){clearTimeout(this._completion_timer),this._completion_timer=null,this._completion_seq+=1,this._completions=[],this._completion_descriptions={},this._completion_index=0,this.requestUpdate()}};customElements.define(`composer-bar`,Dn);var On=class extends M{static properties={option:{attribute:!1}};createRenderRoot(){return this}updated(){let e=this.querySelector(`select`),t=this.option?.currentValue;e&&t!=null&&e.value!==String(t)&&(e.value=String(t))}render(){let e=this.option,t=Array.isArray(e.options)?e.options:[];return T`
      <label class="picker" title=${e.name||e.id}>
        <span class="picker-label">${e.name||e.id}</span>
        <select
          class="select picker-select"
          data-config-id=${e.id}
          aria-label=${e.name||e.id}
          @change=${this._on_change}
        >
          ${t.map(t=>this._render_choice(t,e.currentValue))}
        </select>
      </label>
    `}_render_choice(e,t){return e?Array.isArray(e.options)?T`
        <optgroup label=${e.name||e.group||``}>
          ${e.options.map(e=>this._render_option(e,t))}
        </optgroup>
      `:this._render_option(e,t):D}_render_option(e,t){let n=String(e.value);return T`
      <option value=${n} ?selected=${t!=null&&String(t)===n} title=${e.description||D}>
        ${e.name||n}
      </option>
    `}async _on_change(e){let t=e.currentTarget,n=this.option.currentValue;!await Q.change_config(this.option.id,t.value)&&n!=null&&(t.value=String(n))}};customElements.define(`config-picker`,On);var kn=class extends M{constructor(){super(),this._store=new J(this,X)}createRenderRoot(){return this}updated(){let e=this.querySelector(`details`),t=this.querySelector(`.logs-body`);e&&e.open&&t&&(t.scrollTop=t.scrollHeight)}render(){let e=this._store.state.logs;return T`
      <details class="logs" id="logs-drawer" @toggle=${this._on_toggle}>
        <summary title="Logs" aria-label="Logs">
          <span class="logs-icon" aria-hidden="true">${it}</span>
          <span class="logs-count" ?hidden=${e.length===0}>${e.length}</span>
        </summary>
        <pre class="logs-body" aria-label="Server log output">${e.join(`
`)}</pre>
      </details>
    `}_on_toggle(){this.requestUpdate()}};customElements.define(`log-drawer`,kn);var An=class extends M{constructor(){super(),this._store=new J(this,X)}createRenderRoot(){return this}render(){let e=this._store.state,t=Y.usage_percent(e),n=Y.usage_level(e),{used:r,size:i,cost:a}=e.usage,o=e.agent.version?`${e.agent.name} ${e.agent.version}`:e.agent.name,s=`Context ${Math.round(t)}% · ${st(r)} / ${st(i)}`+(a?` · ${ct(a)}`:``)+` · ${o}`;return T`
      <div class="usage" title=${s} aria-label=${s}>
        <span class="usage-text">${Math.round(t)}%</span>
        <span
          class="usage-bar"
          role="progressbar"
          aria-label="Context usage"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow=${Math.round(t)}
        >
          <span class="usage-fill" data-level=${n} style="width: ${t.toFixed(1)}%"></span>
        </span>
      </div>
    `}};customElements.define(`usage-meter`,An);var jn=[{id:`skills`,label:`Skills`},{id:`mcp`,label:`MCP`},{id:`context`,label:`Context`}],Mn=class extends M{static properties={open:{type:Boolean},tab:{type:String}};constructor(){super(),this.open=!1,this.tab=`skills`,this._store=new J(this,X),this._path=``,this._error=``,this._busy=!1}createRenderRoot(){return this}willUpdate(e){e.has(`open`)&&this.open&&Q.refresh_state()}render(){return this.open?T`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card modal-card--wide"
          role="dialog"
          aria-modal="true"
          aria-label="Session registries"
          @click=${this._stop}
        >
          <div class="modal-tabs" role="tablist">
            ${F(jn,e=>e.id,e=>T`
                <button
                  type="button"
                  class="modal-tab"
                  role="tab"
                  data-active=${this.tab===e.id}
                  aria-selected=${this.tab===e.id}
                  @click=${()=>this._select_tab(e.id)}
                >
                  ${e.label}
                </button>
              `)}
          </div>
          <div class="modal-body">${this._render_body(this._store.state)}</div>
          ${this._error?T`<p class="modal-error">${this._error}</p>`:D}
          <div class="modal-actions">
            <button type="button" class="modal-btn" @click=${this._close}>Done</button>
          </div>
        </div>
      </div>
    `:D}_render_body(e){switch(this.tab){case`mcp`:return this._render_servers(e.mcp_servers||[]);case`context`:return this._render_context(e.context_files||[]);default:return this._render_skills(e.skills||[])}}_render_skills(e){return e.length?T`
      <ul class="registry-modal-list">
        ${e.map(e=>{let t=e.name||e.id||String(e),n=e.loaded??e.enabled??e.status===`loaded`;return T`
            <li class="registry-modal-row">
              <span class="status-dot" data-status=${n?`ready`:`idle`}></span>
              <span class="registry-modal-name" title=${t}>${t}</span>
              <button
                type="button"
                class="modal-btn modal-btn--small"
                @click=${()=>this._act(`skills`,n?`remove`:`load`,t)}
              >
                ${n?`Remove`:`Load`}
              </button>
            </li>
          `})}
      </ul>
    `:T`<p class="modal-empty">No skills are available.</p>`}_render_servers(e){return e.length?T`
      <ul class="registry-modal-list">
        ${e.map(e=>{let t=e.name||e.id||String(e),n=e.connected??e.status===`connected`;return T`
            <li class="registry-modal-row">
              <span class="status-dot" data-status=${n?`ready`:`idle`}></span>
              <span class="registry-modal-name" title=${t}>${t}</span>
              <button
                type="button"
                class="modal-btn modal-btn--small"
                @click=${()=>this._act(`mcp`,n?`disconnect`:`connect`,t)}
              >
                ${n?`Disconnect`:`Connect`}
              </button>
            </li>
          `})}
      </ul>
    `:T`<p class="modal-empty">No MCP servers are configured.</p>`}_render_context(e){return T`
      <div class="modal-inline-form">
        <input
          type="text"
          .value=${this._path}
          placeholder="Relative or absolute file path"
          @input=${this._on_path}
          @keydown=${this._on_path_keydown}
        />
        <button type="button" class="modal-btn modal-btn--small" @click=${this._add_context}>
          Add
        </button>
      </div>
      ${e.length?T`
            <ul class="registry-modal-list">
              ${e.map(e=>{let t=e.path||e.name||String(e);return T`
                  <li class="registry-modal-row">
                    <span class="registry-modal-name" title=${t}>${t}</span>
                    ${e.readOnly||e.read_only?T`<span class="registry-tag">read-only</span>`:D}
                    <button
                      type="button"
                      class="modal-btn modal-btn--small"
                      @click=${()=>this._remove_context(t)}
                    >
                      Remove
                    </button>
                  </li>
                `})}
            </ul>
          `:T`<p class="modal-empty">No context files are attached.</p>`}
    `}_select_tab(e){this.tab=e,this._error=``,this.requestUpdate()}_on_backdrop(){this._busy||this._close()}_stop(e){e.stopPropagation()}_on_path(e){this._path=e.target.value}_on_path_keydown(e){e.key!==`Enter`||e.isComposing||(e.preventDefault(),this._add_context())}async _act(e,t,n){this._busy=!0,this._error=``;try{await Q.registry_action(e,t,n)}catch(e){this._error=e.message,Q.refresh_state()}finally{this._busy=!1,this.requestUpdate()}}async _add_context(){let e=this._path.trim();e&&(await this._act(`context`,`add`,e),this._path=``,this.requestUpdate())}async _remove_context(e){await this._act(`context`,`remove`,e)}_close(){this._busy=!1,this._error=``,this._path=``,this.open=!1,this.dispatchEvent(new CustomEvent(`close`,{bubbles:!0,composed:!0}))}};customElements.define(`registry-modal`,Mn);var Nn=class extends M{static properties={open:{type:Boolean},option:{attribute:!1}};constructor(){super(),this.open=!1,this.option=null,this._query=``,this._error=``,this._busy=!1}createRenderRoot(){return this}willUpdate(e){e.has(`open`)&&this.open&&(this._query=``,this._error=``)}updated(){if(!this.open)return;let e=this.querySelector(`.model-search`);e&&document.activeElement!==e&&e.focus()}render(){if(!this.open||!this.option)return D;let e=this._filtered_items(),t=String(this.option.currentValue||``);return T`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card modal-card--wide"
          role="dialog"
          aria-modal="true"
          aria-labelledby="model-dialog-title"
          @click=${this._stop}
        >
          <h2 id="model-dialog-title">Choose model</h2>
          <input
            class="model-search"
            type="search"
            .value=${this._query}
            placeholder="Search models…"
            aria-label="Search models"
            @input=${this._on_query}
            @keydown=${this._on_keydown}
          />
          <p class="modal-hint">${e.length} model${e.length===1?``:`s`}</p>
          ${e.length?T`
                <ul class="registry-modal-list model-list">
                  ${e.map(e=>T`
                      <li>
                        <button
                          type="button"
                          class="registry-modal-row model-row"
                          data-active=${String(e.value)===t}
                          ?disabled=${this._busy}
                          @click=${()=>this._select(e.value)}
                        >
                          <span class="registry-modal-name" title=${e.value}>${e.name}</span>
                          ${e.group?T`<span class="model-group">${e.group}</span>`:D}
                          ${String(e.value)===t?T`<span class="registry-tag">current</span>`:D}
                        </button>
                      </li>
                    `)}
                </ul>
              `:T`<p class="modal-empty">No models match that search.</p>`}
          ${this._error?T`<p class="modal-error">${this._error}</p>`:D}
          <div class="modal-actions">
            <button type="button" class="modal-btn" @click=${this._close}>Cancel</button>
          </div>
        </div>
      </div>
    `}_on_backdrop(){this._busy||this._close()}_stop(e){e.stopPropagation()}_on_query(e){this._query=e.target.value,this.requestUpdate()}_on_keydown(e){if(e.key===`Escape`)e.preventDefault(),e.stopPropagation(),this._close();else if(e.key===`Enter`&&!e.isComposing){e.preventDefault();let t=this._filtered_items();t.length&&this._select(t[0].value)}}async _select(e){if(!this._busy){this._busy=!0,this._error=``;try{if(!await Q.change_config(this.option.id,String(e)))throw Error(`The bridge rejected the model change`);this._close()}catch(e){this._error=e.message}finally{this._busy=!1,this.requestUpdate()}}}_close(){this._query=``,this._error=``,this._busy=!1,this.open=!1,this.dispatchEvent(new CustomEvent(`close`,{bubbles:!0,composed:!0}))}_filtered_items(){let e=this._query.trim().toLowerCase();return this._items().filter(t=>!e||[t.value,t.name,t.description,t.group].filter(Boolean).some(t=>String(t).toLowerCase().includes(e)))}_items(){let e=Array.isArray(this.option?.options)?this.option.options:[],t=[];for(let n of e)if(Array.isArray(n.options))for(let e of n.options)e&&e.value!==void 0&&t.push({...e,group:n.name||n.group||``});else n&&n.value!==void 0&&t.push({...n,group:``});return t}};customElements.define(`model-dialog`,Nn);var Pn=class extends M{constructor(){super(),this._store=new J(this,X),this._modal=null,this._model_open=!1}createRenderRoot(){return this}render(){let e=this._store.state;return T`
      <div class="control-strip" role="toolbar" aria-label="Session controls">
        <div class="strip-config">
          ${this._render_model(e)}
          ${this._render_pickers(e)}
        </div>
        <div class="strip-badges">
          <button
            type="button"
            class="strip-badge"
            title="Manage skills, MCP servers and context"
            @click=${()=>this._open_modal(`skills`)}
          >
            Extensions
            <span>${e.skills.length+e.mcp_servers.length+e.context_files.length}</span>
          </button>
          ${e.auto_scroll?D:T`<button
                type="button"
                class="strip-badge jump-badge"
                title="Jump to latest"
                @click=${this._jump_latest}
              >
                <span aria-hidden="true">↓</span> Jump to latest
              </button>`}
        </div>
        <div class="strip-actions">
          <usage-meter></usage-meter>
          <log-drawer></log-drawer>
          <button
            class="strip-btn"
            type="button"
            title="New chat"
            aria-label="New chat"
            ?disabled=${e.new_chat_pending}
            @click=${this._new_chat}
          >${at}</button>
          <button
            class="strip-btn"
            type="button"
            title="Restart cecli"
            aria-label="Restart cecli"
            ?disabled=${e.restart_pending}
            @click=${this._restart}
          >${ot}</button>
        </div>
      </div>
      <registry-modal
        .open=${!!this._modal}
        .tab=${this._modal||`skills`}
        @close=${this._close_modal}
      ></registry-modal>
      <model-dialog
        .open=${this._model_open}
        .option=${this._model_option(this._store.state)}
        @close=${this._close_models}
      ></model-dialog>
    `}_new_chat(){Q.new_chat()}_restart(){Q.restart_server()}_jump_latest(){Q.jump_to_latest()}_open_modal(e){this._modal=e,Q.refresh_state(),this.requestUpdate()}_close_modal(){this._modal=null,this.requestUpdate()}_render_model(e){let t=this._model_option(e);return t?T`
      <button
        type="button"
        class="model-trigger"
        title="Search and choose a model"
        @click=${this._open_models}
      >
        <span class="model-trigger-value">${this._model_label(t)}</span>
      </button>
    `:D}_render_pickers(e){let t=e.config_options.filter(e=>e.id!==`mode`&&e.id!==`model`&&e.id!==`reasoning_effort`);return t.length?F(t,e=>e.id,e=>T`<config-picker .option=${e}></config-picker>`):e.status===`ready`&&this._model_option(e)?D:T`<span class="strip-muted">${e.status===`ready`?`No config options`:`Connecting…`}</span>`}_model_option(e){return e.config_options.find(e=>e.id===`model`)||null}_model_label(e){let t=String(e.currentValue??``),n=[];for(let t of e.options||[])Array.isArray(t.options)?n.push(...t.options):t&&t.value!==void 0&&n.push(t);return n.find(e=>String(e.value)===t)?.name||t||`Choose model`}_open_models(){this._model_open=!0,Q.refresh_state(),this.requestUpdate()}_close_models(){this._model_open=!1,this.requestUpdate()}};customElements.define(`control-strip`,Pn);var Fn=class extends M{static properties={entry:{attribute:!1}};createRenderRoot(){return this}render(){let e=this.entry,t=e.options||[],n=e.resolving||e.resolved;return T`
      <article
        class="permission-card ${e.resolving?`is-submitting`:``} ${e.resolved?`is-resolved`:``}"
        data-request-id=${e.key}
      >
        <div class="perm-head">
          <span class="perm-icon" aria-hidden="true">${et}</span>
          <div class="perm-titles">
            <h3 class="perm-title">Permission requested</h3>
            <p class="perm-tool">${e.tool_call.title||`Tool request`}</p>
          </div>
        </div>
        <p class="perm-question">
          ${e.detail||`cecli is asking for permission to continue.`}
        </p>
        <div class="perm-options">
          ${t.length?t.map(t=>T`
                  <button
                    class="perm-option ${_t(t.kind)} ${e.chosen===String(t.optionId)?`is-chosen`:``}"
                    type="button"
                    data-option-id=${String(t.optionId)}
                    ?disabled=${n}
                    @click=${this._choose}
                  >${t.name||String(t.optionId)}</button>
                `):T`
                <button
                  class="perm-option perm-option--reject"
                  type="button"
                  ?disabled=${n}
                  @click=${this._dismiss}
                >Dismiss</button>
              `}
        </div>
        <p
          class="perm-status"
          ?hidden=${!e.resolved}
          data-kind=${e.status_kind}
        >${e.status_text}</p>
      </article>
    `}_choose(e){let t=e.currentTarget;this._emit(t.dataset.optionId)}_dismiss(){this._emit(null)}_emit(e){this.entry.resolving||this.entry.resolved||this.dispatchEvent(new CustomEvent(`permission-resolve`,{bubbles:!0,composed:!0,detail:{request_id:this.entry.request_id,option_id:e}}))}};customElements.define(`permission-card`,Fn);var In=class extends M{constructor(){super(),this._store=new J(this,X)}createRenderRoot(){return this}render(){let e=this._store.state.permissions;return T`
      <div class="permission-region" ?hidden=${e.length===0}>
        ${F(e,e=>e.key,e=>T`
            <permission-card
              .entry=${e}
              @permission-resolve=${this._on_resolve}
            ></permission-card>
          `)}
      </div>
    `}_on_resolve(e){let{request_id:t,option_id:n}=e.detail;Q.resolve_permission(t,n)}};customElements.define(`permission-region`,In);var Ln=class extends M{static properties={open:{type:Boolean}};constructor(){super(),this.open=!1,this._path=``,this._name=``,this._error=``,this._busy=!1}createRenderRoot(){return this}willUpdate(e){e.has(`open`)&&this.open&&!this._path&&(this._path=X.state.workspace||``)}updated(){if(!this.open)return;let e=this.querySelector(`.modal-field input`);e&&document.activeElement!==e&&e.focus()}render(){return this.open?T`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="session-dialog-title"
          @click=${this._stop}
        >
          <h2 id="session-dialog-title">New session</h2>
          <label class="modal-field">
            <span>Workspace path</span>
            <input
              type="text"
              .value=${this._path}
              placeholder="/path/to/project"
              @input=${this._on_path}
            />
          </label>
          <label class="modal-field">
            <span>Session name</span>
            <input
              type="text"
              .value=${this._name}
              placeholder="Optional label"
              @input=${this._on_name}
            />
          </label>
          ${this._error?T`<p class="modal-error">${this._error}</p>`:D}
          <div class="modal-actions">
            <button type="button" class="modal-btn" @click=${this._close}>Cancel</button>
            <button
              type="button"
              class="modal-btn modal-btn--primary"
              ?disabled=${this._busy}
              @click=${this._submit}
            >
              ${this._busy?`Creating…`:`Create`}
            </button>
          </div>
        </div>
      </div>
    `:D}_on_backdrop(){this._busy||this._close()}_on_path(e){this._path=e.target.value}_on_name(e){this._name=e.target.value}_stop(e){e.stopPropagation()}async _submit(){let e=this._path.trim();if(!e)this._error=`A workspace path is required`;else{this._busy=!0,this._error=``;try{if(!await Q.create_session(e,this._name.trim()||null))throw Error(`The bridge did not create a session`);this._close()}catch(e){this._error=e.message}finally{this._busy=!1,this.requestUpdate()}}}_close(){this._path=``,this._name=``,this._error=``,this._busy=!1,this.open=!1,this.dispatchEvent(new CustomEvent(`close`,{bubbles:!0,composed:!0}))}};customElements.define(`session-dialog`,Ln);var Rn=class extends M{constructor(){super(),this._store=new J(this,X)}createRenderRoot(){return this}render(){let e=this._store.state,t=e.workflows||[];return T`
      <aside class="session-sidebar" aria-label="Sessions and registries">
        <div class="sidebar-head">
          <span class="sidebar-title">Sessions</span>
          <button
            class="sidebar-add"
            type="button"
            title="New session"
            ?disabled=${e.sessions.length>=e.max_sessions}
            @click=${this._create}
          >+</button>
        </div>

        <div class="session-tree">
          ${e.sessions.length?F(e.sessions,e=>e.bridgeId,t=>this._render_session(t,e.active_bridge_id)):T`<p class="sidebar-empty">No sessions yet</p>`}
        </div>

        <div class="sidebar-workflows">
          <div class="sidebar-workflows-head">
            <span class="sidebar-title">Workflows</span>
            <span class="sidebar-count">${t.length}</span>
          </div>
          ${t.length?T`
                <ul class="workflow-list">
                  ${F(t,e=>e.name||e.id||String(e),e=>this._render_workflow(e))}
                </ul>
              `:T`<p class="sidebar-empty">No workflows registered</p>`}
        </div>
      </aside>
    `}_render_session(e,t){let n=this._store.state,r=e.bridgeId===t,i=this._activity_for(e,r),a=(n.subagents||[]).filter(e=>!e.removed),o=r&&a.length?a:e.subagents||[];return T`
      <div class="session-node ${r?`is-active`:``}">
        <div class="session-row" @click=${()=>Q.switch_session(e.bridgeId)}>
          <span class="status-dot" data-status=${e.status} aria-hidden="true"></span>
          <span class="session-name" title=${e.workspace||``}>${e.title}</span>
          <span class="activity-badge" data-activity=${i}>${i}</span>
          ${e.permissionCount?T`<span class="permission-badge" title="Pending permissions">${e.permissionCount}</span>`:D}
          <button
            class="session-close"
            type="button"
            title=${e.primary?`Primary session`:`Close session`}
            ?hidden=${e.primary}
            ?disabled=${e.busy}
            @click=${t=>this._close(t,e.bridgeId)}
          >×</button>
        </div>

        ${o.length?T`
              <ul class="subagent-tree">
                ${F(o,e=>e.sessionId,t=>this._render_subagent(e,t))}
              </ul>
            `:D}

      </div>
    `}_create(){this.dispatchEvent(new CustomEvent(`new-session`,{bubbles:!0,composed:!0}))}_close(e,t){e.stopPropagation(),Q.close_session(t).catch(e=>z(X,e.message,`error`))}_render_workflow(e){let t=e.name||e.id||String(e);return T`
      <li>
        <button
          type="button"
          class="workflow-row"
          title=${e.description||e.title||`Run ${t}`}
          @click=${()=>Q.registry_action(`workflows`,`run`,t)}
        >
          <span class="workflow-name">${t}</span>
          <span class="workflow-run">Run</span>
        </button>
      </li>
    `}_select_agent(e,t){Q.select_agent(e,t.sessionId)}_render_subagent(e,t){let n=this._store.state,r=(e.bridgeId===n.active_bridge_id?(n.subagents||[]).find(e=>e.sessionId===t.sessionId):null)||t,i=r.running?`running`:r.state||`idle`;return T`
      <li
        class="subagent-row"
        title="Open this agent's transcript"
        @click=${()=>this._select_agent(e.bridgeId,r)}
      >
        <span
          class="status-dot"
          data-status=${r.running?`ready`:`idle`}
          aria-hidden="true"
        ></span>
        <span class="subagent-name">
          ${r.title||r.name||r.sessionId}
        </span>
        <span class="subagent-state" data-activity=${i}>${i}</span>
      </li>
    `}_activity_for(e,t){let n=this._store.state;if(!t)return e.activity||e.status||`idle`;let r=(n.subagents||[]).filter(e=>!e.removed);return n.turn_state===`requires_action`?`requires action`:n.busy||r.some(e=>e.running)?`running`:n.activity&&n.activity!==`starting`?n.activity:e.activity||e.status||`idle`}};customElements.define(`session-sidebar`,Rn);var zn=Fe(class extends Ie{constructor(e){if(super(e),e.type!==Pe.ATTRIBUTE||e.name!==`class`||e.strings?.length>2)throw Error("`classMap()` can only be used in the `class` attribute and must be the only part in the attribute.")}render(e){return` `+Object.keys(e).filter(t=>e[t]).join(` `)+` `}update(e,[t]){if(this.st===void 0){this.st=new Set,e.strings!==void 0&&(this.nt=new Set(e.strings.join(` `).split(/\s/).filter(e=>e!==``)));for(let e in t)t[e]&&!this.nt?.has(e)&&this.st.add(e);return this.render(t)}let n=e.element.classList;for(let e of this.st)e in t||(n.remove(e),this.st.delete(e));for(let e in t){let r=!!t[e];r===this.st.has(e)||this.nt?.has(e)||(r?(n.add(e),this.st.add(e)):(n.remove(e),this.st.delete(e)))}return E}}),Bn=class extends M{constructor(){super(),this._store=new J(this,X)}createRenderRoot(){return this}render(){return T`
      <div class="toasts" aria-live="polite" aria-atomic="false">
        ${F(this._store.state.toasts,e=>e.id,e=>T`
            <div
              class=${zn({"toast-item":!0,"toast-item--error":e.kind===`error`,"toast-item--info":e.kind!==`error`,"is-visible":e.visible})}
              role="status"
            >${e.message}</div>
          `)}
      </div>
    `}};customElements.define(`toast-stack`,Bn);var Vn=class extends Ie{constructor(e){if(super(e),this.it=D,e.type!==Pe.CHILD)throw Error(this.constructor.directiveName+`() can only be used in child bindings`)}render(e){if(e===D||e==null)return this._t=void 0,this.it=e;if(e===E)return e;if(typeof e!=`string`)throw Error(this.constructor.directiveName+`() called with a non-string value`);if(e===this.it)return this._t;this.it=e;let t=[e];return t.raw=t,this._t={_$litType$:this.constructor.resultType,strings:t,values:[]}}};Vn.directiveName=`unsafeHTML`,Vn.resultType=1;var Hn=Fe(Vn);function Un(e){return String(e??``).replace(/&/g,`&amp;`).replace(/</g,`&lt;`).replace(/>/g,`&gt;`).replace(/"/g,`&quot;`).replace(/'/g,`&#39;`)}function Wn(e){let t=Un(e).split(`
`),n=[],r=0;for(;r<t.length;){let e=t[r];if(!e.trim()){r+=1;continue}let i=/^```([\w+#.-]*)\s*$/.exec(e.trim());if(i){let e=i[1]||``,a=[];for(r+=1;r<t.length&&!/^```\s*$/.test(t[r].trim());)a.push(t[r]),r+=1;r<t.length&&(r+=1),n.push(Kn(a.join(`
`),e));continue}let a=/^(#{1,3})\s+(.+)$/.exec(e);if(a){let e=a[1].length;n.push(`<h${e}>${$(a[2])}</h${e}>`),r+=1;continue}if(/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(e)){n.push(`<hr>`),r+=1;continue}if(/^\s*&gt;\s?/.test(e)){let e=[];for(;r<t.length&&/^\s*&gt;\s?/.test(t[r]);)e.push(t[r].replace(/^\s*&gt;\s?/,``)),r+=1;n.push(`<blockquote>${$(e.join(`
`)).replace(/\n/g,`<br>`)}</blockquote>`);continue}if(/^\s*[-*+]\s+/.test(e)){let e=[];for(;r<t.length&&/^\s*[-*+]\s+/.test(t[r]);)e.push($(t[r].replace(/^\s*[-*+]\s+/,``))),r+=1;n.push(`<ul>${e.map(e=>`<li>${e}</li>`).join(``)}</ul>`);continue}if(/^\s*\d+[.)]\s+/.test(e)){let e=[];for(;r<t.length&&/^\s*\d+[.)]\s+/.test(t[r]);)e.push($(t[r].replace(/^\s*\d+[.)]\s+/,``))),r+=1;n.push(`<ol>${e.map(e=>`<li>${e}</li>`).join(``)}</ol>`);continue}let o=[];for(;r<t.length&&t[r].trim()&&!Gn(t[r]);)o.push(t[r]),r+=1;o.length?n.push(`<p>${$(o.join(`
`)).replace(/\n/g,`<br>`)}</p>`):r+=1}return n.join(``)}function Gn(e){return/^```/.test(e.trim())||/^#{1,3}\s+/.test(e)||/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(e)||/^\s*&gt;\s?/.test(e)||/^\s*[-*+]\s+/.test(e)||/^\s*\d+[.)]\s+/.test(e)}function Kn(e,t){return`<div class="code-block"><div class="code-head"><span class="code-lang">${t?Un(t):`text`}</span><button type="button" class="code-copy" aria-label="Copy code">Copy</button></div><pre><code>${e}</code></pre></div>`}function $(e){return e.split(/(`[^`\n]+`)/g).map((e,t)=>t%2==1?`<code>${e.slice(1,-1)}</code>`:qn(e)).join(``)}function qn(e){let t=[],n=e.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,(e,n,r)=>(t.push({label:n,url:r}),`\u0000link${t.length-1}\u0000`));return n=Jn(n),n=n.replace(/\u0000link(\d+)\u0000/g,(e,n)=>{let r=t[Number(n)];return r?`<a href="${r.url}" target="_blank" rel="noopener noreferrer">${Jn(r.label)}</a>`:``}),n}function Jn(e){return e.replace(/\*\*([^*]+)\*\*/g,`<strong>$1</strong>`).replace(/__([^_]+)__/g,`<strong>$1</strong>`).replace(/~~([^~]+)~~/g,`<del>$1</del>`).replace(/(^|[^*])\*([^*\n]+)\*/g,`$1<em>$2</em>`).replace(/(^|[^\w])_([^_\n]+)_(?!\w)/g,`$1<em>$2</em>`)}var Yn=class extends M{static properties={text:{type:String},streaming:{type:Boolean}};constructor(){super(),this.text=``,this.streaming=!1,this._rendered=``,this._timer=null,this._caret_for=null}createRenderRoot(){return this}willUpdate(e){(e.has(`text`)||e.has(`streaming`))&&(this.streaming?this._schedule_render():this._render_now())}updated(){this.streaming?this._attach_caret():this._remove_caret()}disconnectedCallback(){clearTimeout(this._timer),this._timer=null,super.disconnectedCallback()}render(){return T`
      <div
        class="md ${this.streaming?`is-streaming`:``}"
        @click=${this._on_click}
      >${Hn(this._rendered)}</div>
    `}_schedule_render(){this._timer||=setTimeout(()=>{this._timer=null,this._rendered=Wn(this.text),this.requestUpdate()},60)}_render_now(){clearTimeout(this._timer),this._timer=null,this._rendered=Wn(this.text)}_attach_caret(){if(this._caret_for===this._rendered)return;let e=this.querySelector(`.md`);if(!e)return;let t=document.createElement(`span`);t.className=`stream-caret`,t.setAttribute(`aria-hidden`,`true`);let n=e.lastElementChild;n&&/^(P|LI|H1|H2|H3|BLOCKQUOTE)$/.test(n.tagName)?n.appendChild(t):e.appendChild(t),this._caret_for=this._rendered}_remove_caret(){for(let e of this.querySelectorAll(`.stream-caret`))e.remove();this._caret_for=null}_on_click(e){let t=e.target.closest(`.code-copy`);t&&this._copy_code(t)}async _copy_code(e){let t=e.closest(`.code-block`),n=t?t.querySelector(`code`):null;if(n){try{await navigator.clipboard.writeText(n.textContent)}catch{Xn(n.textContent)}Zn(e,`Copied`)}}};function Xn(e){let t=document.createElement(`textarea`);t.value=e,t.setAttribute(`readonly`,`readonly`),t.style.position=`fixed`,t.style.opacity=`0`,document.body.appendChild(t),t.select();try{document.execCommand(`copy`)}catch{return}finally{t.remove()}}function Zn(e,t){let n=e.textContent;e.textContent=t,setTimeout(()=>{e.isConnected&&(e.textContent=n)},1400)}customElements.define(`markdown-view`,Yn);var Qn=class extends M{static properties={part:{attribute:!1}};createRenderRoot(){return this}render(){let e=this.part.entries||[],t=e.filter(e=>e.status===`completed`).length;return T`
      <article class="plan-card" ?hidden=${e.length===0}>
        <div class="plan-head">
          <span>Plan</span>
          <span class="plan-count badge badge-ghost">${t}/${e.length}</span>
        </div>
        <ul class="plan-list">
          ${e.map(e=>T`
              <li class="plan-item" data-status=${e.status}>
                <span class="plan-mark" aria-hidden="true"></span>
                <span class="plan-text">${e.content}</span>
              </li>
            `)}
        </ul>
      </article>
    `}};customElements.define(`plan-card`,Qn);var $n=class extends M{static properties={item:{attribute:!1},agentId:{type:String}};constructor(){super(),this._open_id=null}createRenderRoot(){return this}render(){let e=this.item.parts.filter(e=>e.type===`thought`||e.type===`tool`),t=this.item.parts.filter(e=>e.type!==`thought`&&e.type!==`tool`);return T`
      <div class="msg msg--assistant" data-turn=${this.item.turn}>
        <div class="msg-body">
          ${e.length?T`<div class="assistant-pills">
                ${F(e,e=>e.id,e=>this._render_pill(e))}
              </div>`:D}
          ${this._render_panel(e.find(e=>e.id===this._open_id))}
          ${F(t,e=>e.id,e=>this._render_part(e))}
        </div>
      </div>
    `}_render_pill(e){let t=e.id===this._open_id;if(e.type===`thought`)return T`
        <button
          type="button"
          class="assistant-pill"
          data-active=${t}
          aria-expanded=${String(t)}
          @click=${()=>this._toggle(e.id)}
        >
          <span class="pill-label">Thinking</span>
          <span class="pill-chevron" aria-hidden="true">${tt}</span>
        </button>
      `;let n=$e[e.kind]||$e.other;return T`
      <button
        type="button"
        class="assistant-pill assistant-pill--tool"
        data-active=${t}
        aria-expanded=${String(t)}
        title=${e.title}
        @click=${()=>this._toggle(e.id)}
      >
        <span class="tool-icon" data-kind=${e.kind} aria-hidden="true">${n}</span>
        <span class="pill-label">${e.title}</span>
        <span
          class="tool-status-dot"
          data-status=${e.status}
          title=${gt(e.status)}
        ></span>
        <span class="pill-chevron" aria-hidden="true">${tt}</span>
      </button>
    `}_render_panel(e){if(!e)return D;if(e.type===`thought`)return T`
        <div class="assistant-pill-panel">
          <div class="pill-panel-body thought-panel-text">${e.text}</div>
        </div>
      `;let t=pt(e.content_text),n=(e.locations||[]).filter(e=>e&&e.path);return T`
      <div class="assistant-pill-panel">
        <div class="pill-panel-head">
          <span>${gt(e.status)}</span>
          ${n.map(e=>T`<span class="tool-loc" title=${e.path}>
              ${bt(e)}
            </span>`)}
        </div>
        ${t?T`<pre><code>${t}</code></pre>`:T`<p class="pill-panel-empty">No output yet.</p>`}
      </div>
    `}_toggle(e){let t=this._open_id!==e;this._open_id=t?e:null,this.requestUpdate(),t&&this.dispatchEvent(new CustomEvent(`transcript-layout`,{bubbles:!0,composed:!0}))}_render_part(e){return e.type===`text`?T`<markdown-view
        .text=${e.text}
        .streaming=${e.streaming}
      ></markdown-view>`:e.type===`plan`?T`<plan-card .part=${e}></plan-card>`:T``}};customElements.define(`assistant-turn`,$n);var er=class extends M{static properties={item:{attribute:!1}};createRenderRoot(){return this}render(){let e=String(this.item.text||``),t=e.split(`
`).find(e=>e.trim())||``;return T`
      <details class="context-message">
        <summary>
          ${this.item.source?T`<span class="context-message-source" title=${`Sent by ${this.item.source}`}>
                ${this.item.source}
              </span>`:``}
          <span class="context-message-preview">${t}</span>
        </summary>
        <div class="context-message-body">${e}</div>
      </details>
    `}};customElements.define(`context-message`,er);var tr=`                     ▒▒╗▒▒╗
 ▒▒▒▒▒╗ ▒▒▒▒▒╗ ▒▒▒▒▒╗▒▒║╚═╝
▒▒╔═══╝▒▒▓▓▓▒║▒▒╔═══╝▒▒║▒▒╗
▒▒║    ▒▒╔═══╝▒▒║    ▒▒║▒▒║
╚▒▒▒▒▒╗╚▒▒▒▒▒╗╚▒▒▒▒▒╗▒▒║▒▒║
 ╚════╝ ╚════╝ ╚════╝╚═╝╚═╝`,nr=class extends M{createRenderRoot(){return this}render(){return T`<pre class="cecli-logo" role="img" aria-label="cecli">${tr}</pre>`}};customElements.define(`brand-logo`,nr);var rr=[{prompt:`Explain the structure of this repository and where I should start reading.`,title:`Explain this repo`},{prompt:`Find a likely bug in the current changes and explain how to fix it.`,title:`Find a bug`},{prompt:`Run the test suite and summarise any failures with likely causes.`,title:`Run the tests`}],ir=class extends M{createRenderRoot(){return this}render(){return T`
      <section class="empty-state">
        <brand-logo></brand-logo>
        <h1>What do you need help with?</h1>
        <p>Ask a question, request a change, or start with one of these.</p>
        <div class="examples">
          ${rr.map(e=>T`
              <button
                class="example"
                type="button"
                data-prompt=${e.prompt}
                @click=${this._on_example}
              >
                <span class="example-glyph" aria-hidden="true"></span>
                <span class="example-text"><strong>${e.title}</strong></span>
              </button>
            `)}
        </div>
      </section>
    `}_on_example(e){let t=e.currentTarget;this.dispatchEvent(new CustomEvent(`example-select`,{bubbles:!0,composed:!0,detail:{prompt:t.dataset.prompt}}))}};customElements.define(`empty-state`,ir);var ar=class extends M{static properties={text:{type:String}};constructor(){super(),this.text=``}createRenderRoot(){return this}render(){return T`
      <div class="msg msg--user">
        <div class="bubble">${this.text}</div>
      </div>
    `}};customElements.define(`user-message`,ar);var or=class extends M{constructor(){super(),this._store=new J(this,X),this._observer=null}createRenderRoot(){return this}firstUpdated(){let e=this._transcript();e&&(this._observer=new MutationObserver(()=>this._maybe_autoscroll()),this._observer.observe(e,{childList:!0,subtree:!0,characterData:!0}),this._resize_observer=new ResizeObserver(()=>this._maybe_autoscroll()),this._resize_observer.observe(e))}disconnectedCallback(){this._observer&&this._observer.disconnect(),this._observer=null,this._resize_observer&&this._resize_observer.disconnect(),this._resize_observer=null,this._scroll_timer&&clearTimeout(this._scroll_timer),this._scroll_timer=null,super.disconnectedCallback()}updated(){this._maybe_autoscroll(),queueMicrotask(()=>this._maybe_autoscroll()),this._scroll_timer&&clearTimeout(this._scroll_timer),this._scroll_timer=setTimeout(()=>{this._scroll_timer=null,this._maybe_autoscroll()},0)}render(){let e=this._store.state,t=Y.visible_transcript(e);return T`
      <div
        class="transcript"
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        tabindex="0"
        @scroll=${this._on_scroll}
        @transcript-layout=${this._maybe_autoscroll}
      >
        ${Y.visible_busy(e)&&t.length===0?T`<p class="history-note">
              This turn is running in the background; earlier transcript history is not
              replayed after a reload.
            </p>`:D}
        <empty-state
          ?hidden=${Y.has_transcript(e)||Y.visible_busy(e)}
          @example-select=${this._on_example}
        ></empty-state>
        ${F(t,e=>e.id,t=>t.type===`user`?T`<user-message .text=${t.text}></user-message>`:t.type===`context`?T`<context-message .item=${t}></context-message>`:T`<assistant-turn
                  .item=${t}
                  .agentId=${e.active_agent_session_id}
                ></assistant-turn>`)}
      </div>
    `}_transcript(){return this.querySelector(`.transcript`)}_near_bottom(){let e=this._transcript();return!e||e.scrollHeight-e.scrollTop-e.clientHeight<80}_scroll_to_bottom(e){let t=this._transcript();t&&t.scrollTo({top:t.scrollHeight,behavior:e?`smooth`:`auto`})}_maybe_autoscroll(){this._store.state.auto_scroll&&this._scroll_to_bottom(!1)}_on_scroll(){let e=this._near_bottom();this._store.state.auto_scroll!==e&&Q.set_auto_scroll(e)}_on_example(e){Q.fill_composer(e.detail&&e.detail.prompt)}};customElements.define(`transcript-view`,or);var sr=class extends M{constructor(){super(),this._session_dialog_open=!1}createRenderRoot(){return this}render(){return T`
      <app-backdrop></app-backdrop>
      <div class="app-shell">
        <app-header></app-header>
        <div class="workspace-shell">
          <session-sidebar @new-session=${this._on_new_session}></session-sidebar>
          <main class="chat-panel">
            <transcript-view></transcript-view>
            <permission-region></permission-region>
            <div class="composer-dock">
              <agent-strip></agent-strip>
              <composer-bar></composer-bar>
              <control-strip></control-strip>
            </div>
          </main>
        </div>
      </div>
      <toast-stack></toast-stack>
      <session-dialog
        .open=${this._session_dialog_open}
        @close=${this._on_session_dialog_close}
      ></session-dialog>
    `}_on_new_session(){this._session_dialog_open=!0,this.requestUpdate()}_on_session_dialog_close(){this._session_dialog_open=!1,this.requestUpdate()}};customElements.define(`cecli-app`,sr),Q.start();