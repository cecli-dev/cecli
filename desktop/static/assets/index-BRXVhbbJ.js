(function(){let e=document.createElement(`link`).relList;if(e&&e.supports&&e.supports(`modulepreload`))return;for(let e of document.querySelectorAll(`link[rel="modulepreload"]`))n(e);new MutationObserver(e=>{for(let t of e)if(t.type===`childList`)for(let e of t.addedNodes)e.tagName===`LINK`&&e.rel===`modulepreload`&&n(e)}).observe(document,{childList:!0,subtree:!0});function t(e){let t={};return e.integrity&&(t.integrity=e.integrity),e.referrerPolicy&&(t.referrerPolicy=e.referrerPolicy),t.credentials=e.crossOrigin===`use-credentials`?`include`:e.crossOrigin===`anonymous`?`omit`:`same-origin`,t}function n(e){if(e.ep)return;e.ep=!0;let n=t(e);fetch(e.href,n)}})();var e=globalThis,t=e.ShadowRoot&&(e.ShadyCSS===void 0||e.ShadyCSS.nativeShadow)&&`adoptedStyleSheets`in Document.prototype&&`replace`in CSSStyleSheet.prototype,n=Symbol(),r=new WeakMap,i=class{constructor(e,t,r){if(this._$cssResult$=!0,r!==n)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=e,this.t=t}get styleSheet(){let e=this.o,n=this.t;if(t&&e===void 0){let t=n!==void 0&&n.length===1;t&&(e=r.get(n)),e===void 0&&((this.o=e=new CSSStyleSheet).replaceSync(this.cssText),t&&r.set(n,e))}return e}toString(){return this.cssText}},a=e=>new i(typeof e==`string`?e:e+``,void 0,n),o=(n,r)=>{if(t)n.adoptedStyleSheets=r.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let t of r){let r=document.createElement(`style`),i=e.litNonce;i!==void 0&&r.setAttribute(`nonce`,i),r.textContent=t.cssText,n.appendChild(r)}},s=t?e=>e:e=>e instanceof CSSStyleSheet?(e=>{let t=``;for(let n of e.cssRules)t+=n.cssText;return a(t)})(e):e,{is:c,defineProperty:l,getOwnPropertyDescriptor:u,getOwnPropertyNames:d,getOwnPropertySymbols:f,getPrototypeOf:p}=Object,m=globalThis,ee=m.trustedTypes,te=ee?ee.emptyScript:``,ne=m.reactiveElementPolyfillSupport,h=(e,t)=>e,re={toAttribute(e,t){switch(t){case Boolean:e=e?te:null;break;case Object:case Array:e=e==null?e:JSON.stringify(e)}return e},fromAttribute(e,t){let n=e;switch(t){case Boolean:n=e!==null;break;case Number:n=e===null?null:Number(e);break;case Object:case Array:try{n=JSON.parse(e)}catch{n=null}}return n}},ie=(e,t)=>!c(e,t),ae={attribute:!0,type:String,converter:re,reflect:!1,useDefault:!1,hasChanged:ie};Symbol.metadata??=Symbol(`metadata`),m.litPropertyMetadata??=new WeakMap;var g=class extends HTMLElement{static addInitializer(e){this._$Ei(),(this.l??=[]).push(e)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(e,t=ae){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(e)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(e,t),!t.noAccessor){let n=Symbol(),r=this.getPropertyDescriptor(e,n,t);r!==void 0&&l(this.prototype,e,r)}}static getPropertyDescriptor(e,t,n){let{get:r,set:i}=u(this.prototype,e)??{get(){return this[t]},set(e){this[t]=e}};return{get:r,set(t){let a=r?.call(this);i?.call(this,t),this.requestUpdate(e,a,n)},configurable:!0,enumerable:!0}}static getPropertyOptions(e){return this.elementProperties.get(e)??ae}static _$Ei(){if(this.hasOwnProperty(h(`elementProperties`)))return;let e=p(this);e.finalize(),e.l!==void 0&&(this.l=[...e.l]),this.elementProperties=new Map(e.elementProperties)}static finalize(){if(this.hasOwnProperty(h(`finalized`)))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(h(`properties`))){let e=this.properties,t=[...d(e),...f(e)];for(let n of t)this.createProperty(n,e[n])}let e=this[Symbol.metadata];if(e!==null){let t=litPropertyMetadata.get(e);if(t!==void 0)for(let[e,n]of t)this.elementProperties.set(e,n)}this._$Eh=new Map;for(let[e,t]of this.elementProperties){let n=this._$Eu(e,t);n!==void 0&&this._$Eh.set(n,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(e){let t=[];if(Array.isArray(e)){let n=new Set(e.flat(1/0).reverse());for(let e of n)t.unshift(s(e))}else e!==void 0&&t.push(s(e));return t}static _$Eu(e,t){let n=t.attribute;return!1===n?void 0:typeof n==`string`?n:typeof e==`string`?e.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(e=>this.enableUpdating=e),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(e=>e(this))}addController(e){(this._$EO??=new Set).add(e),this.renderRoot!==void 0&&this.isConnected&&e.hostConnected?.()}removeController(e){this._$EO?.delete(e)}_$E_(){let e=new Map,t=this.constructor.elementProperties;for(let n of t.keys())this.hasOwnProperty(n)&&(e.set(n,this[n]),delete this[n]);e.size>0&&(this._$Ep=e)}createRenderRoot(){let e=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return o(e,this.constructor.elementStyles),e}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(e=>e.hostConnected?.())}enableUpdating(e){}disconnectedCallback(){this._$EO?.forEach(e=>e.hostDisconnected?.())}attributeChangedCallback(e,t,n){this._$AK(e,n)}_$ET(e,t){let n=this.constructor.elementProperties.get(e),r=this.constructor._$Eu(e,n);if(r!==void 0&&!0===n.reflect){let i=(n.converter?.toAttribute===void 0?re:n.converter).toAttribute(t,n.type);this._$Em=e,i==null?this.removeAttribute(r):this.setAttribute(r,i),this._$Em=null}}_$AK(e,t){let n=this.constructor,r=n._$Eh.get(e);if(r!==void 0&&this._$Em!==r){let e=n.getPropertyOptions(r),i=typeof e.converter==`function`?{fromAttribute:e.converter}:e.converter?.fromAttribute===void 0?re:e.converter;this._$Em=r;let a=i.fromAttribute(t,e.type);this[r]=a??this._$Ej?.get(r)??a,this._$Em=null}}requestUpdate(e,t,n,r=!1,i){if(e!==void 0){let a=this.constructor;if(!1===r&&(i=this[e]),n??=a.getPropertyOptions(e),!((n.hasChanged??ie)(i,t)||n.useDefault&&n.reflect&&i===this._$Ej?.get(e)&&!this.hasAttribute(a._$Eu(e,n))))return;this.C(e,t,n)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(e,t,{useDefault:n,reflect:r,wrapped:i},a){n&&!(this._$Ej??=new Map).has(e)&&(this._$Ej.set(e,a??t??this[e]),!0!==i||a!==void 0)||(this._$AL.has(e)||(this.hasUpdated||n||(t=void 0),this._$AL.set(e,t)),!0===r&&this._$Em!==e&&(this._$Eq??=new Set).add(e))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let e=this.scheduleUpdate();return e!=null&&await e,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[e,t]of this._$Ep)this[e]=t;this._$Ep=void 0}let e=this.constructor.elementProperties;if(e.size>0)for(let[t,n]of e){let{wrapped:e}=n,r=this[t];!0!==e||this._$AL.has(t)||r===void 0||this.C(t,void 0,n,r)}}let e=!1,t=this._$AL;try{e=this.shouldUpdate(t),e?(this.willUpdate(t),this._$EO?.forEach(e=>e.hostUpdate?.()),this.update(t)):this._$EM()}catch(t){throw e=!1,this._$EM(),t}e&&this._$AE(t)}willUpdate(e){}_$AE(e){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(e)),this.updated(e)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(e){return!0}update(e){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(e){}firstUpdated(e){}};g.elementStyles=[],g.shadowRootOptions={mode:`open`},g[h(`elementProperties`)]=new Map,g[h(`finalized`)]=new Map,ne?.({ReactiveElement:g}),(m.reactiveElementVersions??=[]).push(`2.1.2`);var oe=globalThis,se=e=>e,ce=oe.trustedTypes,le=ce?ce.createPolicy(`lit-html`,{createHTML:e=>e}):void 0,ue=`$lit$`,_=`lit$${Math.random().toFixed(9).slice(2)}$`,de=`?`+_,fe=`<${de}>`,v=document,y=()=>v.createComment(``),b=e=>e===null||typeof e!=`object`&&typeof e!=`function`,pe=Array.isArray,me=e=>pe(e)||typeof e?.[Symbol.iterator]==`function`,he=`[ 	
\f\r]`,x=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,ge=/-->/g,_e=/>/g,S=RegExp(`>|${he}(?:([^\\s"'>=/]+)(${he}*=${he}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,`g`),ve=/'/g,ye=/"/g,be=/^(?:script|style|textarea|title)$/i,C=(e=>(t,...n)=>({_$litType$:e,strings:t,values:n}))(1),w=Symbol.for(`lit-noChange`),T=Symbol.for(`lit-nothing`),xe=new WeakMap,E=v.createTreeWalker(v,129);function Se(e,t){if(!pe(e)||!e.hasOwnProperty(`raw`))throw Error(`invalid template strings array`);return le===void 0?t:le.createHTML(t)}var Ce=(e,t)=>{let n=e.length-1,r=[],i,a=t===2?`<svg>`:t===3?`<math>`:``,o=x;for(let t=0;t<n;t++){let n=e[t],s,c,l=-1,u=0;for(;u<n.length&&(o.lastIndex=u,c=o.exec(n),c!==null);)u=o.lastIndex,o===x?c[1]===`!--`?o=ge:c[1]===void 0?c[2]===void 0?c[3]!==void 0&&(o=S):(be.test(c[2])&&(i=RegExp(`</`+c[2],`g`)),o=S):o=_e:o===S?c[0]===`>`?(o=i??x,l=-1):c[1]===void 0?l=-2:(l=o.lastIndex-c[2].length,s=c[1],o=c[3]===void 0?S:c[3]===`"`?ye:ve):o===ye||o===ve?o=S:o===ge||o===_e?o=x:(o=S,i=void 0);let d=o===S&&e[t+1].startsWith(`/>`)?` `:``;a+=o===x?n+fe:l>=0?(r.push(s),n.slice(0,l)+ue+n.slice(l)+_+d):n+_+(l===-2?t:d)}return[Se(e,a+(e[n]||`<?>`)+(t===2?`</svg>`:t===3?`</math>`:``)),r]},we=class e{constructor({strings:t,_$litType$:n},r){let i;this.parts=[];let a=0,o=0,s=t.length-1,c=this.parts,[l,u]=Ce(t,n);if(this.el=e.createElement(l,r),E.currentNode=this.el.content,n===2||n===3){let e=this.el.content.firstChild;e.replaceWith(...e.childNodes)}for(;(i=E.nextNode())!==null&&c.length<s;){if(i.nodeType===1){if(i.hasAttributes())for(let e of i.getAttributeNames())if(e.endsWith(ue)){let t=u[o++],n=i.getAttribute(e).split(_),r=/([.?@])?(.*)/.exec(t);c.push({type:1,index:a,name:r[2],strings:n,ctor:r[1]===`.`?De:r[1]===`?`?Oe:r[1]===`@`?ke:O}),i.removeAttribute(e)}else e.startsWith(_)&&(c.push({type:6,index:a}),i.removeAttribute(e));if(be.test(i.tagName)){let e=i.textContent.split(_),t=e.length-1;if(t>0){i.textContent=ce?ce.emptyScript:``;for(let n=0;n<t;n++)i.append(e[n],y()),E.nextNode(),c.push({type:2,index:++a});i.append(e[t],y())}}}else if(i.nodeType===8){if(i.data===de)c.push({type:2,index:a});else{let e=-1;for(;(e=i.data.indexOf(_,e+1))!==-1;)c.push({type:7,index:a}),e+=_.length-1}}a++}}static createElement(e,t){let n=v.createElement(`template`);return n.innerHTML=e,n}};function D(e,t,n=e,r){if(t===w)return t;let i=r===void 0?n._$Cl:n._$Co?.[r],a=b(t)?void 0:t._$litDirective$;return i?.constructor!==a&&(i?._$AO?.(!1),a===void 0?i=void 0:(i=new a(e),i._$AT(e,n,r)),r===void 0?n._$Cl=i:(n._$Co??=[])[r]=i),i!==void 0&&(t=D(e,i._$AS(e,t.values),i,r)),t}var Te=class{constructor(e,t){this._$AV=[],this._$AN=void 0,this._$AD=e,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(e){let{el:{content:t},parts:n}=this._$AD,r=(e?.creationScope??v).importNode(t,!0);E.currentNode=r;let i=E.nextNode(),a=0,o=0,s=n[0];for(;s!==void 0;){if(a===s.index){let t;s.type===2?t=new Ee(i,i.nextSibling,this,e):s.type===1?t=new s.ctor(i,s.name,s.strings,this,e):s.type===6&&(t=new Ae(i,this,e)),this._$AV.push(t),s=n[++o]}a!==s?.index&&(i=E.nextNode(),a++)}return E.currentNode=v,r}p(e){let t=0;for(let n of this._$AV)n!==void 0&&(n.strings===void 0?n._$AI(e[t]):(n._$AI(e,n,t),t+=n.strings.length-2)),t++}},Ee=class e{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(e,t,n,r){this.type=2,this._$AH=T,this._$AN=void 0,this._$AA=e,this._$AB=t,this._$AM=n,this.options=r,this._$Cv=r?.isConnected??!0}get parentNode(){let e=this._$AA.parentNode,t=this._$AM;return t!==void 0&&e?.nodeType===11&&(e=t.parentNode),e}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(e,t=this){e=D(this,e,t),b(e)?e===T||e==null||e===``?(this._$AH!==T&&this._$AR(),this._$AH=T):e!==this._$AH&&e!==w&&this._(e):e._$litType$===void 0?e.nodeType===void 0?me(e)?this.k(e):this._(e):this.T(e):this.$(e)}O(e){return this._$AA.parentNode.insertBefore(e,this._$AB)}T(e){this._$AH!==e&&(this._$AR(),this._$AH=this.O(e))}_(e){this._$AH!==T&&b(this._$AH)?this._$AA.nextSibling.data=e:this.T(v.createTextNode(e)),this._$AH=e}$(e){let{values:t,_$litType$:n}=e,r=typeof n==`number`?this._$AC(e):(n.el===void 0&&(n.el=we.createElement(Se(n.h,n.h[0]),this.options)),n);if(this._$AH?._$AD===r)this._$AH.p(t);else{let e=new Te(r,this),n=e.u(this.options);e.p(t),this.T(n),this._$AH=e}}_$AC(e){let t=xe.get(e.strings);return t===void 0&&xe.set(e.strings,t=new we(e)),t}k(t){pe(this._$AH)||(this._$AH=[],this._$AR());let n=this._$AH,r,i=0;for(let a of t)i===n.length?n.push(r=new e(this.O(y()),this.O(y()),this,this.options)):r=n[i],r._$AI(a),i++;i<n.length&&(this._$AR(r&&r._$AB.nextSibling,i),n.length=i)}_$AR(e=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);e!==this._$AB;){let t=se(e).nextSibling;se(e).remove(),e=t}}setConnected(e){this._$AM===void 0&&(this._$Cv=e,this._$AP?.(e))}},O=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(e,t,n,r,i){this.type=1,this._$AH=T,this._$AN=void 0,this.element=e,this.name=t,this._$AM=r,this.options=i,n.length>2||n[0]!==``||n[1]!==``?(this._$AH=Array(n.length-1).fill(new String),this.strings=n):this._$AH=T}_$AI(e,t=this,n,r){let i=this.strings,a=!1;if(i===void 0)e=D(this,e,t,0),a=!b(e)||e!==this._$AH&&e!==w,a&&(this._$AH=e);else{let r=e,o,s;for(e=i[0],o=0;o<i.length-1;o++)s=D(this,r[n+o],t,o),s===w&&(s=this._$AH[o]),a||=!b(s)||s!==this._$AH[o],s===T?e=T:e!==T&&(e+=(s??``)+i[o+1]),this._$AH[o]=s}a&&!r&&this.j(e)}j(e){e===T?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,e??``)}},De=class extends O{constructor(){super(...arguments),this.type=3}j(e){this.element[this.name]=e===T?void 0:e}},Oe=class extends O{constructor(){super(...arguments),this.type=4}j(e){this.element.toggleAttribute(this.name,!!e&&e!==T)}},ke=class extends O{constructor(e,t,n,r,i){super(e,t,n,r,i),this.type=5}_$AI(e,t=this){if((e=D(this,e,t,0)??T)===w)return;let n=this._$AH,r=e===T&&n!==T||e.capture!==n.capture||e.once!==n.once||e.passive!==n.passive,i=e!==T&&(n===T||r);r&&this.element.removeEventListener(this.name,this,n),i&&this.element.addEventListener(this.name,this,e),this._$AH=e}handleEvent(e){typeof this._$AH==`function`?this._$AH.call(this.options?.host??this.element,e):this._$AH.handleEvent(e)}},Ae=class{constructor(e,t,n){this.element=e,this.type=6,this._$AN=void 0,this._$AM=t,this.options=n}get _$AU(){return this._$AM._$AU}_$AI(e){D(this,e)}},je={M:ue,P:_,A:de,C:1,L:Ce,R:Te,D:me,V:D,I:Ee,H:O,N:Oe,U:ke,B:De,F:Ae},Me=oe.litHtmlPolyfillSupport;Me?.(we,Ee),(oe.litHtmlVersions??=[]).push(`3.3.3`);var Ne=(e,t,n)=>{let r=n?.renderBefore??t,i=r._$litPart$;if(i===void 0){let e=n?.renderBefore??null;r._$litPart$=i=new Ee(t.insertBefore(y(),e),e,void 0,n??{})}return i._$AI(e),i},Pe=globalThis,k=class extends g{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let e=super.createRenderRoot();return this.renderOptions.renderBefore??=e.firstChild,e}update(e){let t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(e),this._$Do=Ne(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return w}};k._$litElement$=!0,k.finalized=!0,Pe.litElementHydrateSupport?.({LitElement:k});var Fe=Pe.litElementPolyfillSupport;Fe?.({LitElement:k}),(Pe.litElementVersions??=[]).push(`4.2.2`);var Ie=class extends k{createRenderRoot(){return this}render(){return C`
      <div class="backdrop" aria-hidden="true">
        <span class="orb orb--indigo"></span>
        <span class="orb orb--violet"></span>
        <span class="orb orb--teal"></span>
        <span class="grain"></span>
      </div>
    `}};customElements.define(`app-backdrop`,Ie);var Le={ATTRIBUTE:1,CHILD:2,PROPERTY:3,BOOLEAN_ATTRIBUTE:4,EVENT:5,ELEMENT:6},Re=e=>(...t)=>({_$litDirective$:e,values:t}),ze=class{constructor(e){}get _$AU(){return this._$AM._$AU}_$AT(e,t,n){this._$Ct=e,this._$AM=t,this._$Ci=n}_$AS(e,t){return this.update(e,t)}update(e,t){return this.render(...t)}},{I:Be}=je,Ve=e=>e,He=()=>document.createComment(``),Ue=(e,t,n)=>{let r=e._$AA.parentNode,i=t===void 0?e._$AB:t._$AA;if(n===void 0)n=new Be(r.insertBefore(He(),i),r.insertBefore(He(),i),e,e.options);else{let t=n._$AB.nextSibling,a=n._$AM,o=a!==e;if(o){let t;n._$AQ?.(e),n._$AM=e,n._$AP!==void 0&&(t=e._$AU)!==a._$AU&&n._$AP(t)}if(t!==i||o){let e=n._$AA;for(;e!==t;){let t=Ve(e).nextSibling;Ve(r).insertBefore(e,i),e=t}}}return n},A=(e,t,n=e)=>(e._$AI(t,n),e),We={},Ge=(e,t=We)=>e._$AH=t,Ke=e=>e._$AH,qe=e=>{e._$AR(),e._$AA.remove()},Je=(e,t,n)=>{let r=new Map;for(let i=t;i<=n;i++)r.set(e[i],i);return r},j=Re(class extends ze{constructor(e){if(super(e),e.type!==Le.CHILD)throw Error(`repeat() can only be used in text expressions`)}dt(e,t,n){let r;n===void 0?n=t:t!==void 0&&(r=t);let i=[],a=[],o=0;for(let t of e)i[o]=r?r(t,o):o,a[o]=n(t,o),o++;return{values:a,keys:i}}render(e,t,n){return this.dt(e,t,n).values}update(e,[t,n,r]){let i=Ke(e),{values:a,keys:o}=this.dt(t,n,r);if(!Array.isArray(i))return this.ut=o,a;let s=this.ut??=[],c=[],l,u,d=0,f=i.length-1,p=0,m=a.length-1;for(;d<=f&&p<=m;)if(i[d]===null)d++;else if(i[f]===null)f--;else if(s[d]===o[p])c[p]=A(i[d],a[p]),d++,p++;else if(s[f]===o[m])c[m]=A(i[f],a[m]),f--,m--;else if(s[d]===o[m])c[m]=A(i[d],a[m]),Ue(e,c[m+1],i[d]),d++,m--;else if(s[f]===o[p])c[p]=A(i[f],a[p]),Ue(e,i[d],i[f]),f--,p++;else if(l===void 0&&(l=Je(o,p,m),u=Je(s,d,f)),l.has(s[d])){if(l.has(s[f])){let t=u.get(o[p]),n=t===void 0?null:i[t];if(n===null){let t=Ue(e,i[d]);A(t,a[p]),c[p]=t}else c[p]=A(n,a[p]),Ue(e,i[d],n),i[t]=null;p++}else qe(i[f]),f--}else qe(i[d]),d++;for(;p<=m;){let t=Ue(e,c[m+1]);A(t,a[p]),c[p++]=t}for(;d<=f;){let e=i[d++];e!==null&&qe(e)}return this.ut=o,Ge(e,c),w}});async function M(e,t){let n;try{n=await fetch(e,{method:`POST`,headers:{"Content-Type":`application/json`},body:JSON.stringify(t===void 0?{}:t)})}catch(e){throw Error(`Network error: ${e.message}`)}let r=null;try{r=await n.json()}catch{r=null}if(!n.ok){let e=r&&(r.error||r.message)?r.error||r.message:`Request failed (${n.status})`;throw Error(e)}return r}async function Ye(e){let t=e?`?bridgeId=${encodeURIComponent(e)}`:``,n=await fetch(`/api/state${t}`,{headers:{Accept:`application/json`}});if(!n.ok)throw Error(`state request failed (${n.status})`);return n.json()}async function Xe(){let e=await fetch(`/api/sessions`,{headers:{Accept:`application/json`}});if(!e.ok)throw Error(`sessions request failed (${e.status})`);return e.json()}async function Ze(e){let t=e?`?bridgeId=${encodeURIComponent(e)}`:``,n=await fetch(`/api/history${t}`,{headers:{Accept:`application/json`}});if(!n.ok)throw Error(`history request failed (${n.status})`);return n.json()}async function Qe(e){let t;try{t=await fetch(e,{headers:{Accept:`application/json`}})}catch(e){throw Error(`Network error: ${e.message}`)}let n=null;try{n=await t.json()}catch{n=null}if(!t.ok){let e=n&&(n.error||n.message)?n.error||n.message:`Request failed (${t.status})`;throw Error(e)}return n}async function $e(e,t){let n;try{n=await fetch(e,{method:`DELETE`,headers:{"Content-Type":`application/json`},body:JSON.stringify(t===void 0?{}:t)})}catch(e){throw Error(`Network error: ${e.message}`)}let r=null;try{r=await n.json()}catch{r=null}if(!n.ok){let e=r&&(r.error||r.message)?r.error||r.message:`Request failed (${n.status})`;throw Error(e)}return r}async function et(e){return Qe(`/api/fs/dirs${e?`?path=${encodeURIComponent(e)}`:``}`)}async function tt(){return Qe(`/api/onboarding/status`)}async function nt(e=null){return Qe(`/api/onboarding/providers${e?`?slug=${encodeURIComponent(e)}`:``}`)}async function rt(){return Qe(`/api/onboarding/copilot`)}async function it(e,t){return M(`/api/complete`,{...e?{bridgeId:e}:{},text:t})}var at=1e3,ot=8e3,st=4600,ct=5e3,lt={read:C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/></svg>`,edit:C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20l4-1 10-10-3-3L5 16z"/><path d="M14 6l3 3M4 20l1-4"/></svg>`,execute:C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 6l6 6-6 6M13 18h6"/></svg>`,search:C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>`,think:C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 1 3.5 10.9c-.4.3-.5.7-.5 1.1H9c0-.4-.1-.8-.5-1.1A6 6 0 0 1 12 3z"/></svg>`,fetch:C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>`,other:C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12l-8-4.5M12 12v9"/></svg>`},ut=C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"/><path d="M9 12l2 2 4-4"/></svg>`,N=C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>`;C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/><circle cx="12" cy="12" r="3.2"/></svg>`;var dt=C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"/></svg>`,ft=C`<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>`,pt=C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h14v16H5z"/><path d="M8 9h8M8 13h8M8 17h5"/></svg>`,mt=C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`,ht=C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 6.7"/><path d="M20 4v7h-7"/></svg>`,gt=C`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h16"/><path d="M7 20v-5M12 20V9M17 20V4"/></svg>`,_t=C`<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="19" r="1.6"/></svg>`;function P(e){let t=Number(e);if(!Number.isFinite(t)||t<0)return`—`;if(t<1e3)return String(Math.round(t));if(t<1e6){let e=t/1e3;return`${e>=100?Math.round(e):yt(e.toFixed(1))}k`}return`${yt((t/1e6).toFixed(1))}m`}function vt(e){if(!e||typeof e.amount!=`number`)return``;let t=typeof e.currency==`string`?e.currency.toUpperCase():``;try{return new Intl.NumberFormat(void 0,{style:`currency`,currency:t,maximumFractionDigits:4}).format(e.amount)}catch{return`${t} ${e.amount.toFixed(4)}`.trim()}}function yt(e){return String(e).replace(/\.0$/,``)}function bt(e){return typeof e.sessionUpdate==`string`?e.sessionUpdate:typeof e.type==`string`?e.type:e.toolCallId&&typeof e.status==`string`?`tool_call_update`:e.toolCallId?`tool_call`:``}function F(e){if(!e)return``;if(typeof e==`string`)return e;if(Array.isArray(e))return e.map(F).filter(Boolean).join(`
`);if(typeof e==`object`){if(typeof e.text==`string`)return e.text;if(e.content)return F(e.content)}return``}function xt(e){let t=typeof e==`string`?e:String(e||``),n=/<context\b([^>]*)>/i.exec(t),r=n?n[1]:``,i=/\bname=["']([^"']+)["']/i.exec(r)?.[1]||``,a=/\bfrom=["']([^"']+)["']/i.exec(r)?.[1]||``;return{text:t.replace(/<context\b[^>]*?\/?>/gi,``).replace(/<\/context\s*>/gi,``).trim(),is_user:i===`user_input`,context_name:i,from:a}}function St(e){let t=typeof e==`string`?e:String(e||``),n=t.trim(),r=/^```[^\n]*\n([\s\S]*?)\n?```$/.exec(n);return r?r[1]:t}function Ct(e){return St(e).replace(/\n{3,}/g,`

`).trimEnd()}function wt(e){let t=String(e||``).toLowerCase();return t===`read`||t===`delete`||t===`move`?`read`:t===`edit`?`edit`:t===`execute`?`execute`:t===`search`?`search`:t===`think`?`think`:t===`fetch`?`fetch`:`other`}function Tt(e){let t={read:`Reading files`,edit:`Editing files`,execute:`Running command`,search:`Searching`,think:`Thinking`,fetch:`Fetching`,other:`Tool call`};return t[e]||t.other}function Et(e){return e===`in_progress`?`In progress`:e===`completed`?`Completed`:e===`failed`?`Failed`:`Pending`}function Dt(e){let t=String(e||``);return t.startsWith(`allow`)?`perm-option--allow`:t.startsWith(`reject`)?`perm-option--reject`:``}function Ot(e){let t=String(e||``).split(/[\\/]/);return t[t.length-1]||String(e||``)}function kt(e){return e?typeof e.line==`number`?e.line:e.line&&typeof e.line.start==`number`?e.line.start:null:null}function At(e){if(!e||!e.path)return``;let t=kt(e);return t?`${Ot(e.path)}:${t}`:Ot(e.path)}var jt=0;function I(e,t,n=`info`){let r=typeof t==`string`?t:String(t),i=`[${new Date().toLocaleTimeString([],{hour12:!1})}] ${String(n||`info`).padEnd(5)} ${r}`;e.update(e=>{let t=[...e.logs,i];return{...e,logs:t.length>200?t.slice(-200):t}})}function L(e,t,n=`info`){jt+=1;let r=jt;e.update(e=>({...e,toasts:[...e.toasts,{id:r,message:String(t),kind:n||`info`,visible:!1}]})),requestAnimationFrame(()=>{e.update(e=>({...e,toasts:e.toasts.map(e=>e.id===r?{...e,visible:!0}:e)}))}),setTimeout(()=>{e.update(e=>({...e,toasts:e.toasts.map(e=>e.id===r?{...e,visible:!1}:e)})),setTimeout(()=>{e.update(e=>({...e,toasts:e.toasts.filter(e=>e.id!==r)}))},260)},st)}function Mt(e,t,n=null){return W(e,n,[...Xt(U(e,n)),{id:H(`user`),type:`user`,text:t}],null)}function Nt(e,t,n=null,r=`Agent message`,i=``){return W(e,n,[...Xt(U(e,n)),{id:H(`context`),type:`context`,text:t,title:r,source:i}],null)}function Pt(e,t=null){let n=R(e,t);return W(n,t,U(n,t).transcript,null,{turn_sequence:n.turn_sequence+1})}function Ft(e,t,n=null){if(!t)return e;let r=z(e,n),i=r?.parts[r.parts.length-1];if(r&&i&&i.type===`text`)return B(e,{...r,had_text:!0,parts:r.parts.map(e=>e.id===i.id?{...e,text:e.text+t,streaming:!0}:e)},n);let a=r&&i&&i.type===`thought`?{state:e,assistant:r}:Yt(e,n),o=Qt({...a.assistant,had_text:!0,parts:[...V(a.assistant.parts),{id:H(`text`),type:`text`,text:t,streaming:!0}]});return B(a.state,o,n)}function It(e,t,n=null){if(!t)return e;let r=z(e,n),i=r?.parts[r.parts.length-1],a=!!(r&&i&&i.type===`thought`),o=a?{state:e,assistant:r}:Yt(e,n),s=a?{...o.assistant,parts:o.assistant.parts.map(e=>e.id===i.id?{...e,text:e.text+t}:e)}:{...o.assistant,parts:[...o.assistant.parts,{id:H(`thought`),type:`thought`,text:t,open:!1,auto_open:!1}]};return B(o.state,s,n)}function Lt(e,t,n,r=null){let i=String(t?.toolCallId);if(!n){let n=Zt(e,r,i);if(n)return B(e,{...n.assistant,parts:n.assistant.parts.map(e=>e.id===n.part.id?en(e,t):e)},r)}let a=Jt(e,r),o=a.assistant.parts.find(e=>e.type===`tool`&&e.tool_id===i);if(o)return B(a.state,{...a.assistant,parts:a.assistant.parts.map(e=>e.id===o.id?en(e,t):e)},r);let s=n?V(a.assistant.parts):a.assistant.parts,c=en($t(i),t);return B(a.state,{...a.assistant,parts:[...s,c]},r)}function Rt(e,t,n=null){let r=String(t?.toolCallId),i=F(t?.content),a=Zt(e,n,r);if(a)return B(e,{...a.assistant,parts:a.assistant.parts.map(e=>e.id===a.part.id?{...e,content_text:e.content_text+i}:e)},n);let o=Jt(e,n),s={...$t(r),content_text:i};return B(o.state,{...o.assistant,parts:[...o.assistant.parts,s]},n)}function zt(e,t,n=null){let r=Jt(e,n),i=Array.isArray(t)?t.map(e=>({content:e?.content||``,status:e?.status||`pending`})):[],a=r.assistant.parts.find(e=>e.type===`plan`);return a?B(r.state,{...r.assistant,parts:r.assistant.parts.map(e=>e.id===a.id?{...e,entries:i}:e)},n):B(r.state,{...r.assistant,parts:[...V(r.assistant.parts),{id:H(`plan`),type:`plan`,entries:i}]},n)}function Bt(e,t,n,r=null){let i=z(e,r);if(!i)return e;let a=i.parts.find(e=>e.id===t);return!a||a.open===n?e:B(e,{...i,parts:i.parts.map(e=>e.id===t?{...e,open:n}:e)},r)}function R(e,t=null){let n=z(e,t);if(!n)return e;let r=B(e,{...n,parts:V(n.parts)},t);return W(r,t,U(r,t).transcript,null)}function Vt(e,t=!0){return{...e,transcript:[],subagent_transcripts:{},subagent_current_assistant_ids:{},active_agent_session_id:null,permissions:[],current_assistant_id:null,turn_sequence:0,auto_scroll:!0,usage:t?{used:0,size:0,cost:null}:e.usage}}function Ht(e,t){let n=t?.bridgeId||e.bridge_id||``,r=n?`${n}:${t?.requestId}`:String(t?.requestId);if(e.permissions.some(e=>e.key===r))return e;let i=t?.toolCall||{},a=F(i.content).trim();return{...e,permissions:[...e.permissions,{key:r,request_id:t?.requestId,tool_call:i,options:Array.isArray(t?.options)?t.options:[],detail:a,resolved:!1,resolving:!1,chosen:null,status_kind:``,status_text:``}]}}function Ut(e,t,n){let r=e.permissions.find(e=>e.key===t);return!r||r.resolving===n?e:{...e,permissions:e.permissions.map(e=>e.key===t?{...e,resolving:n}:e)}}function Wt(e,t,n){let r=e.permissions.find(e=>e.key===t);if(!r||r.resolved)return e;let i=n==null?null:String(n),a=r.options.find(e=>String(e.optionId)===i)||null;return{...e,permissions:e.permissions.map(e=>e.key===t?{...e,resolved:!0,resolving:!1,chosen:i,status_kind:a?String(a.kind||``):`dismissed`,status_text:i===null?`Dismissed`:a?a.name:`Selected`}:e)}}function Gt(e,t){return e.permissions.some(e=>e.key===t)?{...e,permissions:e.permissions.filter(e=>e.key!==t)}:e}function Kt(e){return e.permissions.length?{...e,permissions:[]}:e}function qt(e){return e.permissions.some(e=>!e.resolved)}function Jt(e,t=null){let n=z(e,t);if(n)return{state:e,assistant:n};let r=U(e,t),i={id:H(`turn`),type:`assistant`,turn:e.turn_sequence,parts:[],had_text:!1};return{state:W(e,t,[...r.transcript,i],i.id),assistant:i}}function z(e,t=null){let n=U(e,t);return n.current_id&&n.transcript.find(e=>e.id===n.current_id)||null}function Yt(e,t=null){let n=U(e,t),r={id:H(`turn`),type:`assistant`,turn:e.turn_sequence,parts:[],had_text:!1};return{state:W(e,t,[...Xt(n),r],r.id),assistant:r}}function Xt(e){return e.current_id?e.transcript.map(t=>t.id===e.current_id&&t.type===`assistant`?{...t,parts:V(t.parts)}:t):e.transcript}function B(e,t,n=null){let r=U(e,n);return W(e,n,r.transcript.map(e=>e.id===t.id?t:e),r.current_id)}function Zt(e,t,n){let r=U(e,t);for(let e=r.transcript.length-1;e>=0;--e){let t=r.transcript[e];if(t.type!==`assistant`)continue;let i=t.parts.find(e=>e.type===`tool`&&e.tool_id===n);if(i)return{assistant:t,part:i}}return null}function Qt(e){let t=e.parts.find(e=>e.type===`thought`);if(!t)return e;let n=t.auto_open&&t.open?!1:t.open;return{...e,parts:e.parts.map(e=>e.id===t.id?{...e,open:n,auto_open:!1}:e)}}function V(e){return e.map(e=>e.type===`text`&&e.streaming?{...e,streaming:!1}:e)}function $t(e){return{id:H(`tool`),type:`tool`,tool_id:e,kind:`other`,title:`Tool call`,status:`pending`,locations:[],content_text:``}}function en(e,t){let n={...e};if(t.kind&&(n.kind=wt(t.kind)),t.title?n.title=t.title:n.title&&n.title!==`Tool call`||(n.title=Tt(n.kind)),t.status&&(n.status=t.status),Array.isArray(t.locations)&&(n.locations=t.locations),t.content!==void 0){let e=F(t.content);e&&(n.content_text=e)}return n}function H(e){return`${e}-${globalThis.crypto?.randomUUID?.()||`${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`}function U(e,t){return t?{transcript:e.subagent_transcripts?.[t]||[],current_id:e.subagent_current_assistant_ids?.[t]||null}:{transcript:e.transcript,current_id:e.current_assistant_id}}function W(e,t,n,r,i={}){return t?{...e,...i,subagent_transcripts:{...e.subagent_transcripts||{},[t]:n},subagent_current_assistant_ids:{...e.subagent_current_assistant_ids||{},[t]:r}}:{...e,...i,transcript:n,current_assistant_id:r}}function tn(e,t,n={}){if(t&&typeof t==`object`)switch(t.type){case`status`:rn(e,t);break;case`session`:an(e,t);break;case`update`:if(!En(e,t))break;on(e,t.update||{},t.sessionId,t.bridgeId);break;case`permission`:if(!Dn(e,t))break;e.update(e=>nn(e,t));break;case`permission_resolved`:ln(e,t,n);break;case`prompt_done`:cn(e,t,n);break;case`log`:I(e,t.message,t.level||`info`);break;case`details`:un(e,t);break;case`subagents`:xn(e,t);break;case`error`:dn(e,t)}}function nn(e,t){let n=Ht(e,t);return n===e?e:{...n,busy:!0,turn_state:`requires_action`,busy_message:`Waiting for your approval`}}function rn(e,t){e.patch_session&&e.patch_session({status:t.status,activity:t.activity,activityDetail:t.detail}),t.agent&&e.update(e=>mn(e,t.agent)),t.detail&&I(e,String(t.detail),`info`),t.status===`exited`&&(e.update(e=>({...Kt(R(e)),busy:!1,stopping:!1,busy_message:``,turn_state:`idle`,retry_available:!!e.last_prompt})),L(e,`cecli exited`,`error`)),pn(e,t.status)}function an(e,t){fn(e,t.sessionId),t.modes&&e.update(e=>({...e,modes:t.modes})),Array.isArray(t.configOptions)&&_n(e,t.configOptions)}function on(e,t,n=null,r=null){if(!t||typeof t!=`object`)return;if(bt(t)===`subagent_update`){bn(e,t,r);return}let i=yn(e.state,n);if(bt(t)===`session_message`){let r=t.recipientSessionId||n,i=t.userMessage?r:n;Cn(e,t,yn(e.state,i))}else switch(bt(t)){case`agent_message_chunk`:e.update(e=>Ft(e,F(t.content),i));break;case`agent_thought_chunk`:e.update(e=>It(e,F(t.content),i));break;case`tool_call`:e.update(e=>Lt(e,t,!0,i));break;case`tool_call_update`:e.update(e=>Lt(e,t,!1,i));break;case`tool_call_content_chunk`:e.update(e=>Rt(e,t,i));break;case`plan`:e.update(e=>zt(e,t.entries,i));break;case`usage_update`:e.update(e=>gn(e,t));break;case`config_option_update`:_n(e,t.configOptions);break;case`current_mode_update`:e.update(e=>vn(e,t.currentModeId));break;case`state_update`:sn(e,t,i)}}function sn(e,t,n=null){let r=t.state;n?(e.update(e=>Sn(e,n,r)),r===`idle`&&e.update(e=>R(e,n))):r===`requires_action`?e.update(e=>({...e,activity:`requires_action`,busy:!0,turn_state:`requires_action`,busy_message:`Waiting for your approval`})):r===`running`?e.update(e=>({...e,activity:`running`,busy:!0,turn_state:`running`,busy_message:`cecli is working…`})):r===`idle`&&e.update(e=>({...R(e),activity:`idle`,busy:!1,stopping:!1,turn_state:`idle`,busy_message:``}))}function cn(e,t,n){e.update(e=>({...Kt(R(e)),activity:`idle`,busy:!1,stopping:!1,turn_state:`idle`,busy_message:``,retry_available:t&&t.stopReason===`cancelled`?!!e.last_prompt:e.retry_available})),t&&t.stopReason===`cancelled`&&I(e,`turn cancelled`,`info`),typeof n.on_prompt_done==`function`&&n.on_prompt_done()}function ln(e,t,n){let r=t.bridgeId||e.state.bridge_id||``,i=r?`${r}:${t.requestId}`:String(t.requestId);e.update(e=>On(Wt(e,i,t.optionId))),typeof n.on_permission_resolved==`function`&&n.on_permission_resolved(i)}function un(e,t){let n=t.details||{};Array.isArray(t.subagents)&&xn(e,t),e.update(e=>{let t={...e,skills:Array.isArray(n.skills)?n.skills:e.skills,mcp_servers:Array.isArray(n.mcpServers)?n.mcpServers:e.mcp_servers,workflows:Array.isArray(n.workflows)?n.workflows:e.workflows,context_files:Array.isArray(n.contextFiles)?n.contextFiles:e.context_files};return n.usage?gn(t,n.usage):t})}function dn(e,t){let n=t.message||`Unknown bridge error`;e.update(e=>({...e,retry_available:!!e.last_prompt})),I(e,n,`error`),L(e,n,`error`)}function fn(e,t){if(!t)return;let n=!1;e.update(e=>e.session_id&&e.session_id!==t?(n=!0,{...Vt(e,!1),session_id:t}):e.session_id===t?e:{...e,session_id:t}),n&&L(e,`Session restarted`,`info`)}function pn(e,t){e.update(e=>{let n=t||e.status,r=n===`exited`;return e.status===n&&(!r||!e.busy)?e:{...e,status:n,busy:!r&&e.busy,stopping:!r&&e.stopping,busy_message:r?``:e.busy_message}})}function mn(e,t){if(!t)return e;let n=t.name||e.agent.name,r=t.version||``;return e.agent.name===n&&e.agent.version===r?e:{...e,agent:{name:n,version:r}}}function hn(e,t){return typeof t!=`string`||!t||e.workspace===t?e:{...e,workspace:t}}function gn(e,t){if(!t||typeof t!=`object`)return e;let n={...e.usage},r=!1;for(let e of[`tokens_sent`,`tokens_received`,`tokens_cached`,`context_used`,`context_size`]){let i=Number(t[e]);Number.isFinite(i)&&n[e]!==i&&(n[e]=i,r=!0)}let i=Number(t.used??t.context_used),a=Number(t.size??t.context_size);return Number.isFinite(i)&&n.used!==i&&(n.used=i,r=!0),Number.isFinite(a)&&n.size!==a&&(n.size=a,r=!0),t.cost!==void 0&&n.cost!==t.cost&&(n.cost=t.cost,r=!0),t.model!==void 0&&n.model!==t.model&&(n.model=t.model,r=!0),t.stats!==void 0&&n.stats!==t.stats&&(n.stats=t.stats,r=!0),r?{...e,usage:n}:e}function _n(e,t){Array.isArray(t)&&e.update(e=>e.config_options===t?e:{...e,config_options:t})}function vn(e,t){if(t==null)return e;let n=String(t),r=!1,i=e.config_options.map(e=>e.id!==`mode`||String(e.currentValue)===n?e:(r=!0,{...e,currentValue:t}));return r?{...e,config_options:i}:e}function yn(e,t){return!t||e.session_id&&t===e.session_id?null:(e.subagents||[]).some(e=>e.sessionId===t)?t:null}function bn(e,t,n=null){let r=t.sessionId;r&&(e.update(e=>{let n=e.subagents||[],i=n.find(e=>e.sessionId===r)||{sessionId:r};if(t.capabilities===null)return{...e,active_agent_session_id:e.active_agent_session_id===r?null:e.active_agent_session_id,subagents:n.map(e=>e.sessionId===r?{...e,removed:!0,running:!1,state:`idle`}:e)};let a={...i,removed:!1};t.title&&(a.title=t.title),t.description&&(a.description=t.description),t.capabilities&&(a.announced=!0),t.state&&typeof t.state==`object`&&(a.state=t.state.state||`idle`,a.running=a.state===`running`,t.state.stopReason&&(a.stopReason=t.state.stopReason),t.state.error&&(a.error=t.state.error));let o=n.some(e=>e.sessionId===r)?n.map(e=>e.sessionId===r?a:e):[...n,a];return{...e,subagents:o,subagent_transcripts:e.subagent_transcripts[r]?e.subagent_transcripts:{...e.subagent_transcripts,[r]:[]}}}),n&&e.patch_session&&e.patch_session(n,{subagents:e.state.subagents}))}function xn(e,t){let n=Array.isArray(t.subagents)?t.subagents:[];e.update(e=>{let t=new Map((e.subagents||[]).map(e=>[e.sessionId,e]));for(let e of n)e?.sessionId&&t.set(e.sessionId,{...t.get(e.sessionId),...e,removed:!1});let r={...e.subagent_transcripts};for(let e of n)e?.sessionId&&!r[e.sessionId]&&(r[e.sessionId]=[]);let i=e.active_agent_session_id&&t.has(e.active_agent_session_id)?e.active_agent_session_id:null;return{...e,active_agent_session_id:i,subagents:[...t.values()],subagent_transcripts:r}}),t.bridgeId&&e.patch_session&&e.patch_session(t.bridgeId,{subagents:n})}function Sn(e,t,n){return{...e,subagents:(e.subagents||[]).map(e=>e.sessionId===t?{...e,state:n,running:n===`running`}:e)}}function Cn(e,t,n){let r=xt(F(t.content));if(!r.text)return;let i=!!t.userMessage||r.is_user,a=wn(r.context_name);e.update(e=>i?Mt(e,r.text,n):Nt(e,r.text,n,a,Tn(e,t.senderSessionId)||r.from))}function wn(e){let t=String(e||``).trim();if(!t)return`Agent message`;let n=t.replace(/[_-]+/g,` `).trim();return n.charAt(0).toUpperCase()+n.slice(1)}function Tn(e,t){if(!t)return``;if(e.session_id&&t===e.session_id)return`Main`;let n=(e.subagents||[]).find(e=>e.sessionId===t);return n?.title||n?.name||String(t)}function En(e,t){if(!t||!t.update)return!1;if(!t.sessionId)return!0;let n=e.state;return n.session_id?t.sessionId===n.session_id||n.subagents.some(e=>e.sessionId===t.sessionId):!1}function Dn(e,t){if(!t||t.requestId===void 0)return!1;if(!t.sessionId)return!0;let n=e.state;return!n.session_id||t.sessionId===n.session_id||n.subagents.some(e=>e.sessionId===t.sessionId)}function On(e){if(qt(e))return e;let t=e.busy?`running`:`idle`,n=e.busy?`cecli is working…`:``;return e.turn_state===t&&e.busy_message===n?e:{...e,turn_state:t,busy_message:n}}function kn(e,t,n=null){if(!t||typeof t!=`object`)return;let r=n||e.active_bridge_id;r&&e.update_for(r,e=>{let n=e,r=Array.isArray(t.messages)?t.messages:[];r.length&&!An(n.transcript)&&(n={...n,transcript:[...jn(r,`main`),...n.transcript],current_assistant_id:null});let i=Array.isArray(t.subagents)?t.subagents:[];if(!i.length)return n;let a=n.subagent_transcripts||{},o=n.subagent_current_assistant_ids||{},s=!1;for(let e of i){let t=e?.sessionId,n=Array.isArray(e?.messages)?e.messages:[];if(!t||!n.length)continue;let r=a[t]||[];An(r)||(a={...a,[t]:[...jn(n,t),...r]},o={...o,[t]:null},s=!0)}return s?{...n,subagent_transcripts:a,subagent_current_assistant_ids:o}:n})}function An(e){return(e||[]).some(e=>e&&(e.type===`user`||e.type===`assistant`))}function jn(e,t){let n=[],r=new Map,i=0;return e.forEach((e,a)=>{let o=String(e?.role||``),s=xt(e?.content).text;if(o===`user`)s&&n.push({id:`${t}-user-${a}`,type:`user`,text:s});else if(o===`assistant`){let o=[],c=xt(e?.reasoning).text;c&&o.push({id:`${t}-thought-${a}`,type:`thought`,text:c,open:!1,auto_open:!1}),s&&o.push({id:`${t}-text-${a}`,type:`text`,text:s,streaming:!1});let l=Array.isArray(e?.toolCalls)?e.toolCalls:[];for(let[e,n]of l.entries()){let i=Mn(`${t}-tool-${a}-${e}`,n);r.set(String(i.tool_id),i),o.push(i)}if(!o.length)return;n.push({id:`${t}-turn-${a}`,type:`assistant`,turn:i++,parts:o,had_text:!!s})}else if(o===`tool`){let o=r.get(String(e?.toolCallId||``));if(o){s&&(o.content_text=o.content_text?`${o.content_text}\n${s}`:s);return}if(!s)return;n.push({id:`${t}-tool-turn-${a}`,type:`assistant`,turn:i++,parts:[{id:`${t}-tool-out-${a}`,type:`tool`,tool_id:String(e?.toolCallId||`tool-${a}`),kind:`other`,title:`Tool result`,status:`completed`,locations:[],content_text:s}],had_text:!1})}}),n}function Mn(e,t){let n=typeof t?.arguments==`string`?t.arguments:JSON.stringify(t?.arguments??``);return{id:e,type:`tool`,tool_id:String(t?.id||e),kind:`other`,title:String(t?.name||`Tool call`),status:`completed`,locations:[],content_text:n}}function Nn(e,t,n=null,r=null){if(!t||typeof t!=`object`)return;let i=n||t.bridgeId||e.active_bridge_id||``;Array.isArray(t.sessions)&&e.set_sessions(t.sessions,t.maxSessions),!e.active_bridge_id&&i&&e.set_active(i);let a=e.scoped(i);if(a.update(e=>hn(e,t.workspace)),a.update(e=>({...e,bridge_id:i})),t.sessionId!==void 0&&a.update(e=>({...e,session_id:t.sessionId})),t.title&&a.update(e=>({...e,title:t.title})),t.agent&&a.update(e=>mn(e,t.agent)),t.modes&&a.update(e=>({...e,modes:t.modes})),Array.isArray(t.configOptions)&&_n(a,t.configOptions),a.update(e=>({...e,activity:t.activity||e.activity,activity_detail:t.activityDetail||``,subagents:Array.isArray(t.subagents)?t.subagents:e.subagents,skills:Array.isArray(t.skills)?t.skills:e.skills,mcp_servers:Array.isArray(t.mcpServers)?t.mcpServers:e.mcp_servers,workflows:Array.isArray(t.workflows)?t.workflows:e.workflows,context_files:Array.isArray(t.contextFiles)?t.contextFiles:e.context_files,details_supported:t.detailsSupported===void 0?e.details_supported:t.detailsSupported})),typeof t.busy==`boolean`&&a.update(e=>{if(t.busy){let t=qt(e);return{...e,busy:!0,stopping:e.stopping,turn_state:t?`requires_action`:`running`,busy_message:e.stopping?`Stopping…`:t?`Waiting for your approval`:`cecli is working…`}}return{...e,busy:!1,stopping:!1,turn_state:`idle`,busy_message:``}}),t.usage&&a.update(e=>gn(e,t.usage)),Array.isArray(t.permissions)){let e=t.permissions;a.update(t=>{let n=new Set(e.map(e=>e.bridgeId||i?`${e.bridgeId||i}:${e.requestId}`:String(e.requestId))),a=t.permissions.filter(e=>r===null?n.has(e.key):!r.has(e.key)||n.has(e.key));return a.length===t.permissions.length?t:{...t,permissions:a}});for(let t of e)a.update(e=>Ht(e,{...t,bridgeId:i}))}pn(a,t.status),a.update(e=>e.stopping?e:On(e))}function G(){return{status:`starting`,busy:!1,busy_message:``,connected:!1,had_connection:!1,disconnect_notified:!1,stopping:!1,workspace:``,bridge_id:null,title:``,sessions:[],active_bridge_id:null,max_sessions:8,activity:`idle`,activity_detail:``,subagents:[],subagent_transcripts:{},subagent_current_assistant_ids:{},active_agent_session_id:null,skills:[],mcp_servers:[],workflows:[],context_files:[],details_supported:null,session_id:null,config_options:[],modes:{},agent:{name:`cecli`,version:``},turn_state:`idle`,usage:{used:0,size:0,cost:null,tokens_sent:0,tokens_received:0,tokens_cached:0,context_used:0,context_size:0,model:null,stats:null},auto_scroll:!0,last_prompt:``,retry_available:!1,draft:``,draft_revision:0,transcript:[],available_commands:[],permissions:[],logs:[],toasts:[],turn_sequence:0,current_assistant_id:null,new_chat_pending:!1,restart_pending:!1,sidebar_open:!0,onboarding:{checked:!1,required:!1,configured:!1,model:null},onboarding_open:!1}}var Pn=class{constructor(e){this._views=new Map([[``,this._strip(e)]]),this._active_bridge_id=null,this._sessions=[],this._max_sessions=e.max_sessions||8,this._revisions=new Map,this._listeners=new Set,this._connection={connected:e.connected,had_connection:e.had_connection,disconnect_notified:e.disconnect_notified}}get state(){return this._project(this._active_bridge_id||``)}get active_bridge_id(){return this._active_bridge_id}get sessions(){return this._sessions}revision(e){return this._revisions.get(e||``)||0}subscribe(e){return this._listeners.add(e),()=>this._listeners.delete(e)}update(e){this._write(this._active_bridge_id||``,e)}update_for(e,t){let n=e||this._active_bridge_id||``;this._write(n,t)}scoped(e){let t=this;return{bridge_id:e,get state(){return t.state_for(e)},update:n=>t.update_for(e,n),patch_session:(n,r)=>r===void 0?t.patch_session(e,n):t.patch_session(n,r)}}state_for(e){let t=e||``;return!this._active_bridge_id||t===this._active_bridge_id?this.state:this._project(t)}set_active(e){let t=e||null;if(t===this._active_bridge_id)return;let n=this.state;if(this._views.set(this._active_bridge_id||``,this._strip(n)),this._active_bridge_id=t,t&&!this._views.has(t)){let e=this._sessions.find(e=>e.bridgeId===t),r=G();r.connected=n.connected,r.had_connection=n.had_connection,r.disconnect_notified=n.disconnect_notified,r.bridge_id=t,r.title=e?.title||``,r.workspace=e?.workspace||``,r.status=e?.status||`starting`,r.session_id=e?.sessionId||null,r.busy=!!e?.busy,r.activity=e?.activity||`idle`,r.activity_detail=e?.activityDetail||``,this._views.set(t,this._strip(r))}this.emit()}set_sessions(e,t){Array.isArray(e)&&(this._sessions=[...e]),Number.isFinite(t)&&(this._max_sessions=t),!this._active_bridge_id&&this._sessions.length?this.set_active(this._sessions[0].bridgeId):this.emit()}remove_session(e){this._views.delete(e),this._sessions=this._sessions.filter(t=>t.bridgeId!==e),this._active_bridge_id===e&&(this._active_bridge_id=this._sessions[0]?.bridgeId||null),this.emit()}patch_session(e,t){if(typeof e==`object`&&e&&t===void 0&&(t=e,e=this._active_bridge_id),!e||!t)return;let n=!1,r=Object.fromEntries(Object.entries(t).filter(([,e])=>e!==void 0));this._sessions=this._sessions.map(t=>t.bridgeId===e?(n=!0,{...t,...r}):t),n&&this.emit()}emit(){this._emit_scheduled||(this._emit_scheduled=!0,queueMicrotask(()=>{this._emit_scheduled=!1;for(let e of this._listeners)e(this.state)}))}_project(e){let t=this._views.get(e);return t||=e?G():this._views.get(``)||G(),{...t,sessions:this._sessions,active_bridge_id:this._active_bridge_id,max_sessions:this._max_sessions,...this._connection}}_write(e,t){let n=this._views.get(e)||G(),r=t(this._project(e));if(!r)return;let i={connected:r.connected,had_connection:r.had_connection,disconnect_notified:r.disconnect_notified},a=i.connected!==this._connection.connected||i.had_connection!==this._connection.had_connection||i.disconnect_notified!==this._connection.disconnect_notified;this._connection=i;let o=this._strip(r),s=!this._same_view(n,o);s&&(this._views.set(e,o),this._revisions.set(e,this.revision(e)+1)),(s||a)&&this.emit()}_same_view(e,t){let n=Object.keys(e);return n.length===Object.keys(t).length&&n.every(n=>e[n]===t[n])}_strip(e){let t={...e};return delete t.sessions,delete t.active_bridge_id,delete t.max_sessions,delete t.connected,delete t.had_connection,delete t.disconnect_notified,t}},K=class{constructor(e,t){this.host=e,this.store=t,this._unsubscribe=null,e.addController(this)}get state(){return this.store.state}hostConnected(){this._unsubscribe=this.store.subscribe(()=>this.host.requestUpdate())}hostDisconnected(){this._unsubscribe&&this._unsubscribe(),this._unsubscribe=null}},q={connection_label(e){let t=e.status||`starting`;return t===`ready`&&e.busy&&(t=`busy`),!e.connected&&e.had_connection&&(t=`reconnecting`),t},turn_label(e){return(e.turn_state||`idle`).replace(/_/g,` `)},busy_text(e){return e.busy_message||`cecli is working…`},retry_visible(e){return!(!e.retry_available||!e.last_prompt||e.busy||e.stopping)},usage_percent(e){let{used:t,size:n}=e.usage;return n>0?Math.min(Math.max(t/n*100,0),100):0},usage_level(e){let t=q.usage_percent(e);return t>90?`high`:t>70?`warn`:`normal`},active_agent(e){return e.active_agent_session_id&&(e.subagents||[]).find(t=>t.sessionId===e.active_agent_session_id)||null},visible_transcript(e){return e.active_agent_session_id?e.subagent_transcripts?.[e.active_agent_session_id]||[]:e.transcript},visible_busy(e){return e.active_agent_session_id?!!q.active_agent(e)?.running:e.busy},has_transcript(e){return q.visible_transcript(e).length>0}},J=new Pn(G()),Y=new class{constructor(){this.socket=null,this.pending=new Map,this.sequence=0,this.open_promise=null}get ready(){return this.socket?.readyState===WebSocket.OPEN}async connect(){return this.ready?!0:(this.open_promise||=new Promise(e=>{let t=window.__CECLI_TOKEN__||``,n=[`cecli.desktop.v1`];t&&n.push(`token.${t}`);let r=window.location.protocol===`https:`?`wss`:`ws`,i;try{i=new WebSocket(`${r}://${window.location.host}/ws`,n)}catch{this.open_promise=null,e(!1);return}this.socket=i,i.onopen=()=>{this.open_promise=null,e(!0)},i.onmessage=e=>this._receive(e.data),i.onclose=()=>{this.socket=null,this.open_promise=null,this._reject_pending(`WebSocket closed`)},i.onerror=()=>{this.open_promise=null,this._reject_pending(`WebSocket error`),e(!1)}}),this.open_promise)}async request(e,t={}){if(!this.ready&&!await this.connect())throw Error(`WebSocket is unavailable`);this.sequence+=1;let n=`c${this.sequence}`;return new Promise((r,i)=>{this.pending.set(n,{resolve:r,reject:i});try{this.socket.send(JSON.stringify({id:n,command:e,params:t}))}catch(e){this.pending.delete(n),i(e)}})}_receive(e){let t;try{t=JSON.parse(e)}catch{return}if(!t||t.id===void 0)return;let n=this.pending.get(t.id);n&&(this.pending.delete(t.id),t.ok?n.resolve(t.result):n.reject(Error(t.error||`WebSocket command failed`)))}_reject_pending(e){for(let t of this.pending.values())t.reject(Error(e));this.pending.clear()}},X=new class{constructor(e){this.store=e,this.event_source=null,this.state_generations=new Map,this.permission_timers=new Map,this.history_loaded=new Set,this.reconnect_timer=null,this.reconnect_delay=at}start(){this.connect(),this.refresh_onboarding(),this.sync_timer=setInterval(()=>this.sync_now(),5e3)}sync_now(){this.store.state.connected&&(this.refresh_sessions(),this.store.state.busy||this.refresh_state(this.store.active_bridge_id),this.hydrate_history(this.store.active_bridge_id))}connect(){clearTimeout(this.reconnect_timer),this.reconnect_timer=null,this.event_source&&this.event_source.close();let e=new EventSource(`/api/events`);this.event_source=e,e.onopen=()=>{this.reconnect_delay=at,this.store.update(e=>({...e,connected:!0,had_connection:!0,disconnect_notified:!1})),this.refresh_sessions(),this.refresh_state(this.store.active_bridge_id)},e.onmessage=e=>{let t;try{t=JSON.parse(e.data)}catch{I(this.store,`malformed event: ${e.data}`,`error`);return}if(t.type===`sessions`){this.store.set_sessions(t.sessions,t.maxSessions),this._sync_active_summary();return}let n=t.bridgeId||this.store.active_bridge_id,r=n?this.store.scoped(n):this.store;if(tn(r,t,{on_permission_resolved:e=>this.schedule_permission_cleanup(e,n),on_prompt_done:()=>this.clear_permission_cleanup(n)}),this._track_session_event(r,t),t.type===`status`&&t.status===`ready`&&this.hydrate_history(n),t.type===`subagents`&&this.hydrate_history(n),t.type===`session`&&n){for(let e of this.history_loaded)e.startsWith(`${n}:`)&&this.history_loaded.delete(e);this.hydrate_history(n)}},e.onerror=()=>{this.event_source===e&&(e.close(),this.event_source=null,this.store.update(e=>({...e,connected:!1})),this.store.state.had_connection&&!this.store.state.disconnect_notified&&(this.store.update(e=>({...e,disconnect_notified:!0})),L(this.store,`Connection lost — reconnecting…`,`error`)),this.schedule_reconnect())}}schedule_reconnect(){if(this.reconnect_timer)return;let e=this.reconnect_delay;this.reconnect_timer=setTimeout(()=>{this.reconnect_timer=null,this.reconnect_delay=Math.min(this.reconnect_delay*2,ot),this.connect()},e)}async refresh_sessions(){try{let e=await Xe();this.store.set_sessions(e.sessions,e.maxSessions),(e.sessions||[]).length||this.store.update(e=>e.status===`idle`?e:{...e,status:`idle`,busy:!1,turn_state:`idle`,activity:`idle`}),this._sync_active_summary()}catch(e){I(this.store,`session list failed: ${e.message}`,`error`)}}_sync_active_summary(){let e=this.store.active_bridge_id;if(!e)return;let t=this.store.sessions.find(t=>t.bridgeId===e);t&&this.store.update_for(e,e=>{let n=Array.isArray(t.subagents)?t.subagents:e.subagents,r={...e.subagent_transcripts};for(let e of n)e?.sessionId&&!r[e.sessionId]&&(r[e.sessionId]=[]);return{...e,subagents:n,subagent_transcripts:r,skills:Array.isArray(t.skills)?t.skills:e.skills,mcp_servers:Array.isArray(t.mcpServers)?t.mcpServers:e.mcp_servers,workflows:Array.isArray(t.workflows)?t.workflows:e.workflows,context_files:Array.isArray(t.contextFiles)?t.contextFiles:e.context_files}})}async refresh_state(e=this.store.active_bridge_id,t=0){if(!e&&(await this.refresh_sessions(),e=this.store.active_bridge_id,!e))return;let n=(this.state_generations.get(e)||0)+1;this.state_generations.set(e,n);let r=this.store.revision(e),i=new Set(this.store.state_for(e).permissions.map(e=>e.key));try{let a=await Ye(e);if(this.state_generations.get(e)!==n)return;if(this.store.revision(e)!==r&&this.store.state_for(e).session_id&&t<1){await this.refresh_state(e,t+1);return}Nn(this.store,a,e,i),this.hydrate_history(e)}catch(e){I(this.store,`state sync failed: ${e.message}`,`error`)}}async hydrate_history(e=this.store.active_bridge_id){let t=e||this.store.active_bridge_id;if(!t)return;let n=this.store.state_for(t);if(n.status!==`ready`)return;let r=[`main`];for(let e of n.subagents||[])e?.sessionId&&!e.removed&&r.push(e.sessionId);let i=r.filter(e=>!An(e===`main`?n.transcript:n.subagent_transcripts?.[e]||[])&&!this.history_loaded.has(`${t}:${e}`));if(!i.length)return;for(let e of i)this.history_loaded.add(`${t}:${e}`);let a=null;try{a=await Y.request(`history.get`,{bridgeId:t})}catch{try{a=await Ze(t)}catch{for(let e of i)this.history_loaded.delete(`${t}:${e}`);return}}kn(this.store,a,t)}async refresh_onboarding(e=!1){try{let t=await tt();return this.store.update(n=>{let r=n.onboarding||{};if(!e&&r.checked&&r.configured===!!t.configured&&r.required===!!t.requires_onboarding)return n;let i=!!t.requires_onboarding;return{...n,onboarding:{checked:!0,required:i,configured:!!t.configured,model:t.model||null},onboarding_open:!r.checked&&i}}),t}catch{return this.store.update(e=>({...e,onboarding:{...e.onboarding||{},checked:!0}})),null}}open_onboarding(){this.store.update(e=>({...e,onboarding_open:!0}))}close_onboarding(){this.store.update(e=>({...e,onboarding_open:!1}))}async configure_provider(e){let t=await M(`/api/onboarding/config`,e);return await this.refresh_onboarding(!0),await this.refresh_sessions(),await this.refresh_state(this.store.active_bridge_id),t}async add_workspace(e,t=null){let n=await M(`/api/workspaces`,{path:e,...t?{name:t}:{}});return await this.refresh_sessions(),n?.bridgeId&&await this.switch_session(n.bridgeId),n}async remove_workspace(e){let t=await $e(`/api/workspaces`,{path:e});return await this.refresh_sessions(),await this.refresh_state(this.store.active_bridge_id),t}async switch_session(e){e&&(this.store.update(e=>({...e,active_agent_session_id:null})),e!==this.store.active_bridge_id&&(this.store.set_active(e),await this.refresh_state(e)))}async create_session(e=null,t=null){let n={...e?{cwd:e}:{},...t?{title:t}:{}},r=null;try{r=(await Y.request(`sessions.create`,n))?.bridgeId||null}catch{r=(await M(`/api/sessions`,n))?.bridgeId||null}return await this.refresh_sessions(),r&&await this.switch_session(r),r}async close_session(e){try{await Y.request(`sessions.close`,{bridgeId:e})}catch{await M(`/api/sessions/close`,{bridgeId:e})}this.store.remove_session(e),await this.refresh_sessions(),await this.refresh_state(this.store.active_bridge_id)}async select_agent(e,t=null){e&&e!==this.store.active_bridge_id&&await this.switch_session(e),this.store.update(e=>({...e,active_agent_session_id:t||null,auto_scroll:!0})),this.hydrate_history(e||this.store.active_bridge_id)}async message_subagent(e,t){let n=this.store.active_bridge_id;n&&(await M(`/api/subagent/message`,{bridgeId:n,sessionId:e,text:t}),this.store.update(t=>({...t,subagents:(t.subagents||[]).map(t=>t.sessionId===e?{...t,running:!0,state:`running`}:t)})))}async registry_action(e,t,n){let r=this.store.active_bridge_id;if(!r)return;let i=e===`workflows`&&t===`run`;try{let i={bridgeId:r,name:n};e===`context`&&(i.path=n),await Y.request(`${e}.${t}`,i)}catch{await M(`/api/${e}`,{bridgeId:r,action:t,name:n})}i&&this.store.update(e=>{let t=`/workflows run ${n}`;return{...Pt(Mt(e,t)),active_agent_session_id:null,last_prompt:t,retry_available:!1,busy:!0,stopping:!1,busy_message:`cecli is working…`,turn_state:`running`}}),await this.refresh_state(r)}async complete(e){let t=this.store.active_bridge_id;try{return await Y.request(`complete.get`,{bridgeId:t,text:e})}catch{return it(t,e)}}async send_prompt(e){let t=String(e||``).trim(),n=this.store.state,r=this.store.active_bridge_id,i=n.active_agent_session_id;if(!r)return L(this.store,`Add a workspace first`,`error`),!1;if(!t)return!1;if(this.store.state.status!==`ready`)return L(this.store,`cecli is not ready yet`,`error`),!1;if(i)try{return await M(`/api/subagent/message`,{bridgeId:r,sessionId:i,text:t}),this.store.update(e=>({...e,subagents:(e.subagents||[]).map(e=>e.sessionId===i?{...e,running:!0,state:`running`}:e)})),!0}catch(e){return L(this.store,e.message,`error`),!1}if(this.store.state.busy)return!1;try{return await M(`/api/prompt`,r?{bridgeId:r,text:t}:{text:t}),this.store.update(e=>({...Pt(Mt(e,t)),last_prompt:t,retry_available:!1,busy:!0,stopping:!1,busy_message:`cecli is working…`,turn_state:`running`})),!0}catch(e){return this.store.update(e=>({...e,last_prompt:t,retry_available:!0})),L(this.store,e.message,`error`),!1}}async cancel_turn(){let e=this.store.state,t=e.active_agent_session_id;if(t){if(!(e.subagents||[]).find(e=>e.sessionId===t)?.running)return;try{await M(`/api/subagent/cancel`,{bridgeId:this.store.active_bridge_id,sessionId:t})}catch(e){L(this.store,e.message,`error`)}}else if(e.busy&&!e.stopping){this.store.update(e=>({...e,stopping:!0,busy_message:`Stopping…`}));try{await M(`/api/cancel`,{bridgeId:this.store.active_bridge_id})}catch(e){this.store.update(e=>({...e,stopping:!1})),L(this.store,e.message,`error`)}}}async new_chat(){if(this.store.state.busy){L(this.store,`Finish or stop the current turn first`,`error`);return}this.clear_permission_cleanup(),this.history_loaded.clear(),this.store.update(e=>({...e,new_chat_pending:!0}));let e=this.store.state.workspace;try{await M(`/api/new_session`,{...this.store.active_bridge_id?{bridgeId:this.store.active_bridge_id}:{},...e?{cwd:e}:{}}),this.store.update(e=>({...Vt(e),session_id:null,busy:!1,stopping:!1,busy_message:``,turn_state:`idle`})),L(this.store,`Started a new chat`,`info`),this.refresh_state()}catch(e){L(this.store,e.message,`error`)}finally{this.store.update(e=>({...e,new_chat_pending:!1}))}}async restart_server(){this.clear_permission_cleanup(),this.history_loaded.clear(),this.store.update(e=>({...e,restart_pending:!0}));try{await M(`/api/restart`,{bridgeId:this.store.active_bridge_id}),this.store.update(e=>({...Vt(e),session_id:null,busy:!1,stopping:!1,busy_message:``,status:`starting`,turn_state:`idle`})),L(this.store,`Restarting cecli…`,`info`)}catch(e){L(this.store,e.message,`error`)}finally{this.store.update(e=>({...e,restart_pending:!1}))}}async change_config(e,t){try{return await M(`/api/config`,{bridgeId:this.store.active_bridge_id,configId:e,value:t}),this.store.update(n=>({...n,config_options:n.config_options.map(n=>n.id===e?{...n,currentValue:t}:n)})),!0}catch(e){return L(this.store,e.message,`error`),!1}}async resolve_permission(e,t){let n=this.store.state,r=n.permissions.find(t=>String(t.request_id)===String(e));if(!r||r.resolving||r.resolved)return;let i=n.bridge_id||this.store.active_bridge_id,a=r.key;this.store.update(e=>Ut(e,a,!0));try{await M(`/api/permission`,{bridgeId:i,requestId:r.request_id,optionId:t}),this.store.update(e=>Wt(e,a,t)),this.store.update(e=>On(e)),this.schedule_permission_cleanup(a,i)}catch(e){let t=this.store.state.permissions.find(e=>e.key===a);if(t&&t.resolved)return;this.store.update(e=>Ut(e,a,!1)),L(this.store,e.message,`error`)}}schedule_permission_cleanup(e,t=this.store.active_bridge_id){if(this.permission_timers.has(e))return;let n=setTimeout(()=>{this.permission_timers.delete(e),this.store.update_for(t,t=>Gt(t,e)),this.store.patch_session(t,{permissionCount:this.store.state_for(t).permissions.filter(e=>!e.resolved).length})},ct);this.permission_timers.set(e,n)}clear_permission_cleanup(e=null){let t=e?`${e}:`:``;for(let[e,n]of this.permission_timers)(!t||e.startsWith(t))&&(clearTimeout(n),this.permission_timers.delete(e))}_track_session_event(e,t){if(e.patch_session){if(t.type===`update`){if(t.sessionId&&t.sessionId!==e.state.session_id)return;let n=t.update||{};n.sessionUpdate===`state_update`&&n.state?e.patch_session({activity:n.state,busy:n.state===`running`||n.state===`requires_action`}):n.sessionUpdate===`tool_call`&&n.title&&e.patch_session({activityDetail:n.title})}else t.type===`permission`||t.type===`permission_resolved`?e.patch_session({permissionCount:e.state.permissions.filter(e=>!e.resolved).length}):t.type===`prompt_done`&&e.patch_session({activity:`idle`,busy:!1,permissionCount:0})}}set_thought_open(e,t,n=null){this.store.update(r=>Bt(r,e,t,n))}set_auto_scroll(e){let t=!!e;this.store.update(e=>e.auto_scroll===t?e:{...e,auto_scroll:t})}jump_to_latest(){this.set_auto_scroll(!0)}fill_composer(e){this.store.update(t=>({...t,draft:String(e||``),draft_revision:t.draft_revision+1}))}}(J),Fn=class extends k{constructor(){super(),this._store=new K(this,J)}createRenderRoot(){return this}render(){let e=this._store.state,t=(e.subagents||[]).filter(e=>!e.removed);if(!t.length)return T;let n=e.active_agent_session_id;return C`
      <div class="agent-strip" role="tablist" aria-label="Agent transcripts">
        <button
          class="agent-pill"
          type="button"
          role="tab"
          data-active=${!n}
          aria-selected=${!n}
          @click=${()=>X.select_agent(e.active_bridge_id,null)}
        >
          <span class="agent-dot" data-status=${e.busy?`running`:`idle`} aria-hidden="true"></span>
          <span class="agent-name">Main</span>
        </button>
        ${j(t,e=>e.sessionId,t=>C`
            <button
              class="agent-pill"
              type="button"
              role="tab"
              data-active=${n===t.sessionId}
              aria-selected=${n===t.sessionId}
              title=${t.description||t.title||t.name||t.sessionId}
              @click=${()=>X.select_agent(e.active_bridge_id,t.sessionId)}
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
    `}};customElements.define(`agent-strip`,Fn);var In={sidebar:C`<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" aria-hidden="true">
    <rect x="1.5" y="2" width="13" height="12" rx="2"></rect>
    <path d="M5.5 2v12"></path>
  </svg>`,chat:C`<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" aria-hidden="true">
    <rect x="1.5" y="2" width="13" height="12" rx="2"></rect>
    <path d="M5.5 2v12M10.5 2v12"></path>
  </svg>`,workbench:C`<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" aria-hidden="true">
    <rect x="1.5" y="2" width="13" height="12" rx="2"></rect>
    <path d="M10.5 2v12"></path>
  </svg>`},Ln=class extends k{static properties={chatCollapsed:{type:Boolean},sidebarCollapsed:{type:Boolean},workbenchCollapsed:{type:Boolean}};constructor(){super(),this.chatCollapsed=!1,this.sidebarCollapsed=!1,this.workbenchCollapsed=!1}createRenderRoot(){return this}render(){return C`
      <header class="topbar">
        <div class="brand">
          <img class="brand-mark" src=${`/static/cecli-temp-logo-favicon.svg`} alt="" aria-hidden="true" />
          <span class="brand-name">cecli</span>
        </div>


        <div class="pane-toggles" role="group" aria-label="Panel visibility">
          <button
            class="pane-toggle"
            type="button"
            data-collapsed=${this.sidebarCollapsed}
            aria-pressed=${!this.sidebarCollapsed}
            aria-label=${this.sidebarCollapsed?`Show sidebar`:`Hide sidebar`}
            title=${this.sidebarCollapsed?`Show sidebar`:`Hide sidebar`}
            @click=${()=>this._toggle_pane(`sidebar`)}
          >${In.sidebar}</button>
          <button
            class="pane-toggle"
            type="button"
            data-collapsed=${this.chatCollapsed}
            aria-pressed=${!this.chatCollapsed}
            aria-label=${this.chatCollapsed?`Show chat`:`Hide chat`}
            title=${this.chatCollapsed?`Show chat`:`Hide chat`}
            @click=${()=>this._toggle_pane(`chat`)}
          >${In.chat}</button>
          <button
            class="pane-toggle"
            type="button"
            data-collapsed=${this.workbenchCollapsed}
            aria-pressed=${!this.workbenchCollapsed}
            aria-label=${this.workbenchCollapsed?`Show browser panel`:`Hide browser panel`}
            title=${this.workbenchCollapsed?`Show browser panel`:`Hide browser panel`}
            @click=${()=>this._toggle_pane(`workbench`)}
          >${In.workbench}</button>
        </div>
      </header>
    `}_toggle_pane(e){this.dispatchEvent(new CustomEvent(`toggle-pane`,{detail:{pane:e},bubbles:!0,composed:!0}))}};customElements.define(`app-header`,Ln);var Rn=class extends k{constructor(){super(),this._store=new K(this,J),this._has_text=!1,this._sending=!1,this._applied_revision=0,this._completions=[],this._completion_descriptions={},this._completion_index=0,this._completion_start=0,this._completion_seq=0,this._completion_timer=null,this._on_global_keydown=this._on_global_keydown.bind(this)}createRenderRoot(){return this}connectedCallback(){super.connectedCallback(),document.addEventListener(`keydown`,this._on_global_keydown)}disconnectedCallback(){document.removeEventListener(`keydown`,this._on_global_keydown),super.disconnectedCallback()}updated(){let e=this._store.state;if(e.draft_revision===this._applied_revision)return;this._applied_revision=e.draft_revision;let t=this._textarea();t&&(t.value=e.draft,this._has_text=e.draft.trim().length>0,this._auto_grow(),t.focus())}render(){let e=this._store.state,t=q.active_agent(e),n=t?!!t.running:e.busy,r=q.retry_visible(e),i=!n&&(this._sending||e.status!==`ready`||!this._has_text);return C`
      <footer class="composer">
        <div class="busy-indicator" ?hidden=${!n}>
          <span class="spinner" aria-hidden="true"></span>
          <span>${q.busy_text(e)}</span>
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
          >${n?ft:dt}</button>
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
              <span>${q.turn_label(e)}</span>
            </span>
          </div>
        </div>
      </footer>
    `}_textarea(){return this.querySelector(`#composer-input`)}_auto_grow(){let e=this._textarea();e&&(e.style.height=`auto`,e.style.height=`${Math.min(e.scrollHeight,180)}px`)}_on_input(){let e=this._textarea();e&&(this._has_text=e.value.trim().length>0,this._auto_grow(),this._schedule_completions(e.value),this.requestUpdate())}_on_keydown(e){if(this._completions.length){if(e.key===`ArrowDown`||e.key===`ArrowUp`){e.preventDefault();let t=e.key===`ArrowDown`?1:-1,n=this._completions.length;this._completion_index=(this._completion_index+t+n)%n,this.requestUpdate();return}if((e.key===`Tab`||e.key===`Enter`)&&!e.shiftKey&&!e.isComposing){e.preventDefault(),this._accept_completion();return}if(e.key===`Escape`){e.preventDefault(),e.stopPropagation(),this._dismiss_completions();return}}e.key!==`Enter`||e.shiftKey||e.isComposing||(e.preventDefault(),this._is_busy()||this._submit())}_on_send_click(){this._is_busy()?X.cancel_turn():this._submit()}async _submit(){let e=this._textarea();if(!e||this._sending)return;let t=e.value.trim();if(!t||!J.state.active_agent_session_id&&J.state.busy)return;this._sending=!0,this.requestUpdate();let n=!1;try{n=await X.send_prompt(t)}finally{this._sending=!1}n&&(e.value=``,this._has_text=!1,this._auto_grow(),this._dismiss_completions()),this.requestUpdate()}_retry(){let e=J.state;if(e.busy||!e.last_prompt)return;let t=this._textarea();t&&(t.value=e.last_prompt,this._has_text=!0,this._auto_grow(),this.requestUpdate(),this._submit())}_on_global_keydown(e){if(e.key!==`Escape`||!this._is_busy())return;let t=this._textarea();document.activeElement===t&&t.value.trim()||(e.preventDefault(),X.cancel_turn())}_is_busy(){let e=J.state,t=e.active_agent_session_id;return t?!!(e.subagents||[]).find(e=>e.sessionId===t)?.running:!!e.busy}_render_completions(){return this._completions.length?C`
      <div class="completion-popover" role="listbox" aria-label="Completions">
        <ul class="completion-list">
          ${this._completions.map((e,t)=>C`
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
                  ${this._completion_descriptions[e]?C`<span class="completion-detail">
                        ${this._completion_descriptions[e]}
                      </span>`:T}
                </button>
              </li>
            `)}
        </ul>
      </div>
    `:T}_schedule_completions(e){if(clearTimeout(this._completion_timer),!e.trim()){this._dismiss_completions();return}let t=++this._completion_seq;this._completion_timer=setTimeout(async()=>{try{let n=await X.complete(e);if(t!==this._completion_seq)return;let r=Array.isArray(n?.suggestions)?n.suggestions:[];this._completions=r,this._completion_descriptions=n?.descriptions||{},this._completion_start=Number.isFinite(n?.start)?n.start:e.length,this._completion_index=0,this.requestUpdate()}catch{t===this._completion_seq&&this._dismiss_completions()}},120)}_select_completion(e){this._completion_index=e,this._accept_completion()}_accept_completion(){let e=this._textarea();if(!e||!this._completions.length)return;let t=e.value,n=String(this._completions[this._completion_index]),r=Math.max(0,Math.min(this._completion_start,t.length)),i=n.startsWith(`/`)&&r===0?`${n} `:n;e.value=t.slice(0,r)+i;let a=e.value.length;e.setSelectionRange(a,a),this._has_text=e.value.trim().length>0,this._auto_grow(),this._dismiss_completions(),e.focus()}_dismiss_completions(){clearTimeout(this._completion_timer),this._completion_timer=null,this._completion_seq+=1,this._completions=[],this._completion_descriptions={},this._completion_index=0,this.requestUpdate()}};customElements.define(`composer-bar`,Rn);var zn=class extends k{static properties={option:{attribute:!1}};createRenderRoot(){return this}updated(){let e=this.querySelector(`select`),t=this.option?.currentValue;e&&t!=null&&e.value!==String(t)&&(e.value=String(t))}render(){let e=this.option,t=Array.isArray(e.options)?e.options:[];return C`
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
    `}_render_choice(e,t){return e?Array.isArray(e.options)?C`
        <optgroup label=${e.name||e.group||``}>
          ${e.options.map(e=>this._render_option(e,t))}
        </optgroup>
      `:this._render_option(e,t):T}_render_option(e,t){let n=String(e.value);return C`
      <option value=${n} ?selected=${t!=null&&String(t)===n} title=${e.description||T}>
        ${e.name||n}
      </option>
    `}async _on_change(e){let t=e.currentTarget,n=this.option.currentValue;!await X.change_config(this.option.id,t.value)&&n!=null&&(t.value=String(n))}};customElements.define(`config-picker`,zn);var Bn=class extends k{constructor(){super(),this._store=new K(this,J)}createRenderRoot(){return this}updated(){let e=this.querySelector(`details`),t=this.querySelector(`.logs-body`);e&&e.open&&t&&(t.scrollTop=t.scrollHeight)}render(){let e=this._store.state.logs;return C`
      <details class="logs" id="logs-drawer" @toggle=${this._on_toggle}>
        <summary title="Logs" aria-label="Logs">
          <span class="logs-icon" aria-hidden="true">${pt}</span>
          <span class="logs-count" ?hidden=${e.length===0}>${e.length}</span>
        </summary>
        <pre class="logs-body" aria-label="Server log output">${e.join(`
`)}</pre>
      </details>
    `}_on_toggle(){this.requestUpdate()}};customElements.define(`log-drawer`,Bn);var Vn={tokens_last_minute:`Tokens last minute`,max_single_request:`Largest request`,requests_per_minute:`Requests per minute`},Hn=[`Tokens last minute`,`Largest request`,`Requests per minute`],Un=class extends k{constructor(){super(),this._store=new K(this,J),this._open=!1,this._pinned=!1}createRenderRoot(){return this}connectedCallback(){super.connectedCallback(),this._on_pointer_down=e=>this._close_outside(e),document.addEventListener(`pointerdown`,this._on_pointer_down,!0)}disconnectedCallback(){document.removeEventListener(`pointerdown`,this._on_pointer_down,!0),super.disconnectedCallback()}render(){let e=this._store.state,t=e.usage||{},n=this._number(t.context_used??t.used),r=this._number(t.context_size??t.size),i=r>0?Math.min(Math.max((n||0)/r*100,0),100):null,a=this._rows(e,t,n,r,i),o=this._render_stats(t.stats),s=`Usage metrics${i===null?``:` \u00b7 context ${Math.round(i)}%`}`;return C`
      <div
        class="strip-menu metrics"
        @mouseenter=${this._on_enter}
        @mouseleave=${this._on_leave}
        @focusin=${this._on_focus_in}
        @focusout=${this._on_focus_out}
        @keydown=${this._on_keydown}
      >
        <button
          type="button"
          class="strip-btn metrics-trigger"
          title=${s}
          aria-label=${s}
          aria-haspopup="true"
          aria-expanded=${this._open?`true`:`false`}
          @click=${this._toggle}
        >
          <span class="metrics-icon" aria-hidden="true">${gt}</span>
          ${i===null?T:C`<span class="metrics-percent">${Math.round(i)}%</span>`}
        </button>
        ${this._open?C`
          <div class="metrics-panel" role="region" aria-label="Usage metrics">
            <div class="strip-menu-head">Token usage</div>
            ${a.length?C`<dl class="metrics-grid">${a}</dl>`:C`<p class="strip-menu-empty">No usage data yet.</p>`}
            ${o}
          </div>
        `:T}
      </div>
    `}_rows(e,t,n,r,i){let a=[],o=this._format_cost(t.cost);if(o&&a.push(this._row(`Total cost`,o)),this._number(t.tokens_sent)!==null&&a.push(this._row(`Tokens sent`,P(t.tokens_sent))),this._number(t.tokens_received)!==null&&a.push(this._row(`Tokens received`,P(t.tokens_received))),this._number(t.tokens_cached)!==null&&a.push(this._row(`Tokens cached`,P(t.tokens_cached))),n!==null&&r!==null&&r>0){let e=i===null?``:` \u00b7 ${Math.round(i)}%`;a.push(this._row(`Context`,`${P(n)} / ${P(r)}${e}`))}let s=t.model||this._model_name(e);return s&&a.push(this._row(`Model`,s)),a}_render_stats(e){if(!e)return T;if(Array.isArray(e)){let t=e.filter(e=>typeof e==`number`);if(!t.length)return T;let n=t.map((e,t)=>this._row(Hn[t]||`Stat ${t+1}`,P(e)));return this._stats_block(n)}if(typeof e!=`object`)return T;let t=Object.entries(e).filter(([,e])=>e!=null);return t.length?t.every(([,e])=>e&&typeof e==`object`&&!Array.isArray(e))?C`<div class="metrics-stats"><h3>Model stats</h3>${t.map(([e,t])=>C`
        <div class="metrics-stats-group">
          <h4>${e}</h4>
          <dl class="metrics-grid">${this._stat_rows(t)}</dl>
        </div>
      `)}</div>`:this._stats_block(this._stat_rows(e)):T}_stats_block(e){return e.length?C`<div class="metrics-stats"><h3>Model stats</h3><dl class="metrics-grid">${e}</dl></div>`:T}_stat_rows(e){return Object.entries(e).filter(([,e])=>e!=null&&typeof e!=`object`).map(([e,t])=>this._row(this._stat_label(e),this._stat_value(t)))}_row(e,t){return C`<div class="metrics-row"><dt>${e}</dt><dd>${t}</dd></div>`}_format_cost(e){return typeof e==`number`&&Number.isFinite(e)?new Intl.NumberFormat(void 0,{style:`currency`,currency:`USD`,maximumFractionDigits:4}).format(e):vt(e)}_number(e){if(e==null||e===``)return null;let t=Number(e);return Number.isFinite(t)&&t>=0?t:null}_model_name(e){let t=(e.config_options||[]).find(e=>e.id===`model`);return t?String(t.currentValue??``):``}_stat_label(e){if(Vn[e])return Vn[e];let t=String(e).replace(/_/g,` `).trim();return t.charAt(0).toUpperCase()+t.slice(1)}_stat_value(e){return typeof e==`number`?P(e):typeof e==`boolean`?e?`Yes`:`No`:String(e)}_open_panel(e=!1){this._pinned=this._pinned||e,this._open||(this._open=!0,this.requestUpdate())}_close_panel(){(this._open||this._pinned)&&(this._open=!1,this._pinned=!1,this.requestUpdate())}_toggle(e){e.stopPropagation(),this._open&&this._pinned?this._close_panel():this._open_panel(!0)}_on_enter(){this._open_panel()}_on_leave(){this._pinned||this._close_panel()}_on_focus_in(){this._open_panel()}_on_focus_out(e){let t=e.relatedTarget;t&&this.contains(t)||this._close_panel()}_on_keydown(e){e.key===`Escape`&&(e.stopPropagation(),this._close_panel(),this.querySelector(`.metrics-trigger`)?.focus())}_close_outside(e){this._open&&(e.composedPath().includes(this)||this._close_panel())}};customElements.define(`metrics-menu`,Un);var Wn=class extends k{constructor(){super(),this._store=new K(this,J),this._open=!1,this._sending=!1}createRenderRoot(){return this}connectedCallback(){super.connectedCallback(),this._on_pointer_down=e=>this._close_outside(e),document.addEventListener(`pointerdown`,this._on_pointer_down,!0)}disconnectedCallback(){document.removeEventListener(`pointerdown`,this._on_pointer_down,!0),super.disconnectedCallback()}render(){let e=this._store.state,t=e.status===`ready`,n=this._sending||e.new_chat_pending||e.busy||!t,r=this._sending||e.restart_pending||e.busy||!t;return C`
      <div
        class="strip-menu actions"
        @focusout=${this._on_focus_out}
        @keydown=${this._on_keydown}
      >
        <button
          type="button"
          class="strip-btn actions-trigger"
          title="Session actions"
          aria-label="Session actions"
          aria-haspopup="menu"
          aria-expanded=${this._open?`true`:`false`}
          @click=${this._toggle}
        >
          <span class="actions-icon" aria-hidden="true">${_t}</span>
        </button>
        ${this._open?C`
          <div class="actions-panel" role="menu" aria-label="Session actions">
            <button
              type="button"
              class="actions-item"
              role="menuitem"
              ?disabled=${n}
              @click=${this._clear}
            >
              <span class="actions-item-icon" aria-hidden="true">${mt}</span>
              <span class="actions-item-text">
                <span class="actions-item-label">Clear</span>
                <span class="actions-item-hint">Send <code>/clear</code></span>
              </span>
            </button>
            <button
              type="button"
              class="actions-item"
              role="menuitem"
              ?disabled=${r}
              @click=${this._reset}
            >
              <span class="actions-item-icon" aria-hidden="true">${ht}</span>
              <span class="actions-item-text">
                <span class="actions-item-label">Reset</span>
                <span class="actions-item-hint">Send <code>/reset</code></span>
              </span>
            </button>
          </div>
        `:T}
      </div>
    `}async _clear(){await this._send(`/clear`)}async _reset(){await this._send(`/reset`)}async _send(e){if(!this._sending){this._sending=!0,this._close_panel();try{await X.send_prompt(e)}finally{this._sending=!1,this.requestUpdate()}}}_toggle(e){e.stopPropagation(),this._open?this._close_panel():(this._open=!0,this.requestUpdate())}_close_panel(){this._open&&(this._open=!1,this.requestUpdate())}_focus_trigger(){this.querySelector(`.actions-trigger`)?.focus()}_on_focus_out(e){let t=e.relatedTarget;t&&this.contains(t)||this._close_panel()}_on_keydown(e){if(e.key===`Escape`){e.stopPropagation(),this._close_panel(),this._focus_trigger();return}if(e.key!==`ArrowDown`&&e.key!==`ArrowUp`)return;let t=[...this.querySelectorAll(`.actions-item:not(:disabled)`)];if(!t.length)return;e.preventDefault();let n=t.indexOf(document.activeElement),r=e.key===`ArrowDown`?1:-1;t[n===-1?0:(n+r+t.length)%t.length].focus()}_close_outside(e){this._open&&(e.composedPath().includes(this)||this._close_panel())}};customElements.define(`actions-menu`,Wn);var Gn=[{id:`skills`,label:`Skills`},{id:`mcp`,label:`MCP`},{id:`context`,label:`Context`}],Kn=class extends k{static properties={open:{type:Boolean},tab:{type:String}};constructor(){super(),this.open=!1,this.tab=`skills`,this._store=new K(this,J),this._path=``,this._error=``,this._busy=!1}createRenderRoot(){return this}willUpdate(e){e.has(`open`)&&this.open&&X.refresh_state()}render(){return this.open?C`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card modal-card--wide"
          role="dialog"
          aria-modal="true"
          aria-label="Session registries"
          @click=${this._stop}
        >
          <div class="modal-tabs" role="tablist">
            ${j(Gn,e=>e.id,e=>C`
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
          ${this._error?C`<p class="modal-error">${this._error}</p>`:T}
          <div class="modal-actions">
            <button type="button" class="modal-btn" @click=${this._close}>Done</button>
          </div>
        </div>
      </div>
    `:T}_render_body(e){switch(this.tab){case`mcp`:return this._render_servers(e.mcp_servers||[]);case`context`:return this._render_context(e.context_files||[]);default:return this._render_skills(e.skills||[])}}_render_skills(e){return e.length?C`
      <ul class="registry-modal-list">
        ${e.map(e=>{let t=e.name||e.id||String(e),n=e.loaded??e.enabled??e.status===`loaded`;return C`
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
    `:C`<p class="modal-empty">No skills are available.</p>`}_render_servers(e){return e.length?C`
      <ul class="registry-modal-list">
        ${e.map(e=>{let t=e.name||e.id||String(e),n=e.connected??e.status===`connected`;return C`
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
    `:C`<p class="modal-empty">No MCP servers are configured.</p>`}_render_context(e){return C`
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
      ${e.length?C`
            <ul class="registry-modal-list">
              ${e.map(e=>{let t=e.path||e.name||String(e);return C`
                  <li class="registry-modal-row">
                    <span class="registry-modal-name" title=${t}>${t}</span>
                    ${e.readOnly||e.read_only?C`<span class="registry-tag">read-only</span>`:T}
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
          `:C`<p class="modal-empty">No context files are attached.</p>`}
    `}_select_tab(e){this.tab=e,this._error=``,this.requestUpdate()}_on_backdrop(){this._busy||this._close()}_stop(e){e.stopPropagation()}_on_path(e){this._path=e.target.value}_on_path_keydown(e){e.key!==`Enter`||e.isComposing||(e.preventDefault(),this._add_context())}async _act(e,t,n){this._busy=!0,this._error=``;try{await X.registry_action(e,t,n)}catch(e){this._error=e.message,X.refresh_state()}finally{this._busy=!1,this.requestUpdate()}}async _add_context(){let e=this._path.trim();e&&(await this._act(`context`,`add`,e),this._path=``,this.requestUpdate())}async _remove_context(e){await this._act(`context`,`remove`,e)}_close(){this._busy=!1,this._error=``,this._path=``,this.open=!1,this.dispatchEvent(new CustomEvent(`close`,{bubbles:!0,composed:!0}))}};customElements.define(`registry-modal`,Kn);var qn=class extends k{static properties={open:{type:Boolean},option:{attribute:!1}};constructor(){super(),this.open=!1,this.option=null,this._query=``,this._error=``,this._busy=!1}createRenderRoot(){return this}willUpdate(e){e.has(`open`)&&this.open&&(this._query=``,this._error=``)}updated(){if(!this.open)return;let e=this.querySelector(`.model-search`);e&&document.activeElement!==e&&e.focus()}render(){if(!this.open||!this.option)return T;let e=this._filtered_items(),t=String(this.option.currentValue||``);return C`
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
          ${e.length?C`
                <ul class="registry-modal-list model-list">
                  ${e.map(e=>C`
                      <li>
                        <button
                          type="button"
                          class="registry-modal-row model-row"
                          data-active=${String(e.value)===t}
                          ?disabled=${this._busy}
                          @click=${()=>this._select(e.value)}
                        >
                          <span class="registry-modal-name" title=${e.value}>${e.name}</span>
                          ${e.group?C`<span class="model-group">${e.group}</span>`:T}
                          ${String(e.value)===t?C`<span class="registry-tag">current</span>`:T}
                        </button>
                      </li>
                    `)}
                </ul>
              `:C`<p class="modal-empty">No models match that search.</p>`}
          ${this._error?C`<p class="modal-error">${this._error}</p>`:T}
          <div class="modal-actions">
            <button type="button" class="modal-btn" @click=${this._open_onboarding}>
              Add provider
            </button>
            <button type="button" class="modal-btn" @click=${this._close}>Cancel</button>
          </div>
        </div>
      </div>
    `}_on_backdrop(){this._busy||this._close()}_stop(e){e.stopPropagation()}_on_query(e){this._query=e.target.value,this.requestUpdate()}_on_keydown(e){if(e.key===`Escape`)e.preventDefault(),e.stopPropagation(),this._close();else if(e.key===`Enter`&&!e.isComposing){e.preventDefault();let t=this._filtered_items();t.length&&this._select(t[0].value)}}async _select(e){if(!this._busy){this._busy=!0,this._error=``;try{if(!await X.change_config(this.option.id,String(e)))throw Error(`The bridge rejected the model change`);this._close()}catch(e){this._error=e.message}finally{this._busy=!1,this.requestUpdate()}}}_open_onboarding(){this.dispatchEvent(new CustomEvent(`open-onboarding`,{bubbles:!0,composed:!0})),this._close()}_close(){this._query=``,this._error=``,this._busy=!1,this.open=!1,this.dispatchEvent(new CustomEvent(`close`,{bubbles:!0,composed:!0}))}_filtered_items(){let e=this._query.trim().toLowerCase();return this._items().filter(t=>!e||[t.value,t.name,t.description,t.group].filter(Boolean).some(t=>String(t).toLowerCase().includes(e)))}_items(){let e=Array.isArray(this.option?.options)?this.option.options:[],t=[];for(let n of e)if(Array.isArray(n.options))for(let e of n.options)e&&e.value!==void 0&&t.push({...e,group:n.name||n.group||``});else n&&n.value!==void 0&&t.push({...n,group:``});return t}};customElements.define(`model-dialog`,qn);var Jn=class extends k{constructor(){super(),this._store=new K(this,J),this._modal=null,this._model_open=!1}createRenderRoot(){return this}render(){let e=this._store.state;return C`
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
          ${e.auto_scroll?T:C`<button
                type="button"
                class="strip-badge jump-badge"
                title="Jump to latest"
                @click=${this._jump_latest}
              >
                <span aria-hidden="true">↓</span> Jump to latest
              </button>`}
        </div>
        <div class="strip-actions">
          <metrics-menu></metrics-menu>
          <log-drawer></log-drawer>
          <actions-menu></actions-menu>
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
    `}_jump_latest(){X.jump_to_latest()}_open_modal(e){this._modal=e,X.refresh_state(),this.requestUpdate()}_close_modal(){this._modal=null,this.requestUpdate()}_render_model(e){let t=this._model_option(e);return t?C`
      <button
        type="button"
        class="model-trigger"
        title="Search and choose a model"
        @click=${this._open_models}
      >
        <span class="model-trigger-value">${this._model_label(t)}</span>
      </button>
    `:T}_render_pickers(e){let t=e.config_options.filter(e=>e.id!==`mode`&&e.id!==`model`&&e.id!==`reasoning_effort`);return t.length?j(t,e=>e.id,e=>C`<config-picker .option=${e}></config-picker>`):e.status===`ready`&&this._model_option(e)?T:C`<span class="strip-muted">${e.status===`ready`?`No config options`:`Connecting…`}</span>`}_model_option(e){return e.config_options.find(e=>e.id===`model`)||null}_model_label(e){let t=String(e.currentValue??``),n=[];for(let t of e.options||[])Array.isArray(t.options)?n.push(...t.options):t&&t.value!==void 0&&n.push(t);return n.find(e=>String(e.value)===t)?.name||t||`Choose model`}_open_models(){this._model_open=!0,X.refresh_state(),this.requestUpdate()}_close_models(){this._model_open=!1,this.requestUpdate()}};customElements.define(`control-strip`,Jn);var Yn=`github_copilot`,Xn=class extends k{static properties={open:{type:Boolean}};constructor(){super(),this.open=!1,this._step=`provider`,this._providers=[],this._provider=null,this._key_values={},this._models=[],this._query=``,this._copilot=null,this._login=null,this._loading=!1,this._busy=!1,this._error=``,this._poll_timer=null}createRenderRoot(){return this}willUpdate(e){e.has(`open`)&&this.open&&(this._reset(),this._providers.length||this._load_providers())}disconnectedCallback(){super.disconnectedCallback(),this._stop_polling()}render(){return this.open?C`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card modal-card--wide onboarding-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="onboarding-title"
          @click=${this._stop}
        >
          <h2 id="onboarding-title">${this._title()}</h2>
          ${this._render_step()}
          ${this._error?C`<p class="modal-error">${this._error}</p>`:T}
          <div class="modal-actions">
            ${this._step===`provider`?T:C`<button type="button" class="modal-btn" @click=${this._back}>Back</button>`}
            <button type="button" class="modal-btn" @click=${this._close}>Cancel</button>
          </div>
        </div>
      </div>
    `:T}_title(){return this._step===`configure`?`Connect ${this._provider?.display_name||`provider`}`:this._step===`copilot`?`Connect GitHub Copilot`:this._step===`models`?`Choose a default model`:`Set up cecli`}_render_step(){return this._loading?C`<p class="modal-empty">Loading\u2026</p>`:this._step===`configure`?this._render_keys():this._step===`copilot`?this._render_copilot():this._step===`models`?this._render_models():this._render_providers()}_render_providers(){return C`
      <p class="modal-hint">Pick a provider. Keys are saved to ~/.cecli/.env; the model goes to conf.yml.</p>
      <ul class="registry-modal-list onboarding-list">
        ${this._providers.map(e=>C`
            <li>
              <button
                type="button"
                class="registry-modal-row onboarding-row"
                @click=${()=>this._choose_provider(e)}
              >
                <span class="registry-modal-name">${e.display_name}</span>
                ${e.slug===Yn?C`<span class="model-group">OAuth</span>`:T}
                ${e.configured?C`<span class="registry-tag">configured</span>`:C`<span class="model-group">${e.api_key_env.join(`, `)||`no key`}</span>`}
              </button>
            </li>
          `)}
      </ul>
    `}_render_keys(){return C`
      <p class="modal-hint">Enter the provider API key values.</p>
      ${(this._provider?.api_key_env||[]).map(e=>C`
          <label class="modal-field">
            <span>${e}</span>
            <input
              type="password"
              .value=${this._key_values[e]||``}
              placeholder=${e}
              @input=${t=>this._on_key(e,t)}
            />
          </label>
        `)}
      <div class="modal-actions">
        <button
          type="button"
          class="modal-btn modal-btn--primary"
          ?disabled=${this._busy}
          @click=${this._continue_keys}
        >
          Continue
        </button>
      </div>
    `}_render_copilot(){let e=this._login||this._copilot?.login||{};return(e.state===`pending`||e.state===`configured`)&&e.verification_uri?C`
        <p class="modal-hint">Open GitHub and enter this code:</p>
        <p class="onboarding-code">${e.user_code||`…`}</p>
        <p class="modal-hint">
          <a href=${e.verification_uri} target="_blank" rel="noreferrer">
            ${e.verification_uri}
          </a>
        </p>
        <p class="modal-hint">Waiting for authorization\u2026</p>
      `:e.state===`error`||e.state===`expired`?C`
        <p class="modal-error">${e.error||`GitHub authorization failed`}</p>
        <div class="modal-actions">
          <button type="button" class="modal-btn modal-btn--primary" @click=${this._start_copilot_login}>
            Try again
          </button>
        </div>
      `:C`
      <p class="modal-hint">
        GitHub Copilot uses OAuth, not an API key. Sign in once and its models become available.
      </p>
      <div class="modal-actions">
        <button
          type="button"
          class="modal-btn modal-btn--primary"
          ?disabled=${this._busy}
          @click=${this._start_copilot_login}
        >
          Sign in with GitHub
        </button>
      </div>
    `}_render_models(){let e=this._filtered_models();return C`
      <input
        class="model-search"
        type="search"
        .value=${this._query}
        placeholder="Search models\u2026"
        aria-label="Search models"
        @input=${this._on_query}
      />
      <p class="modal-hint">${e.length} model${e.length===1?``:`s`}</p>
      ${e.length?C`
            <ul class="registry-modal-list model-list onboarding-list">
              ${e.map(e=>C`
                  <li>
                    <button
                      type="button"
                      class="registry-modal-row model-row"
                      ?disabled=${this._busy}
                      @click=${()=>this._select_model(e)}
                    >
                      <span class="registry-modal-name" title=${e}>${e}</span>
                    </button>
                  </li>
                `)}
            </ul>
          `:C`
            <p class="modal-empty">No models were discovered.</p>
            <label class="modal-field">
              <span>Model name</span>
              <input
                type="text"
                placeholder="provider/model-name"
                @keydown=${this._on_manual_model}
              />
            </label>
            <p class="modal-hint">Type a model name and press Enter.</p>
          `}
    `}async _load_providers(){this._loading=!0,this._error=``,this.requestUpdate();try{let e=await nt();this._providers=e.providers||[]}catch(e){this._error=e.message}finally{this._loading=!1,this.requestUpdate()}}async _choose_provider(e){this._provider=e,this._key_values={},this._error=``,e.slug===Yn?await this._open_copilot():e.requires_key&&!e.configured?(this._step=`configure`,this.requestUpdate()):await this._load_models()}async _open_copilot(){this._loading=!0,this._step=`copilot`,this.requestUpdate();try{if(this._copilot=await rt(),this._login=this._copilot.login||null,this._copilot.configured){await this._load_models();return}}catch(e){this._error=e.message}finally{this._loading=!1,this.requestUpdate()}}async _start_copilot_login(){this._busy=!0,this._error=``,this.requestUpdate();try{let e=await M(`/api/onboarding/copilot/login`,{});this._login=e,this._start_polling()}catch(e){this._error=e.message}finally{this._busy=!1,this.requestUpdate()}}_start_polling(){this._stop_polling(),this._poll_timer=setInterval(()=>this._poll_copilot(),2500)}_stop_polling(){this._poll_timer&&clearInterval(this._poll_timer),this._poll_timer=null}async _poll_copilot(){try{let e=await rt();if(this._copilot=e,this._login=e.login||this._login,e.configured){this._stop_polling(),await this._load_models();return}this._login&&[`error`,`expired`].includes(this._login.state)&&this._stop_polling(),this.requestUpdate()}catch(e){this._stop_polling(),this._error=e.message,this.requestUpdate()}}_on_key(e,t){this._key_values[e]=t.target.value}async _continue_keys(){let e=(this._provider.api_key_env||[]).filter(e=>!String(this._key_values[e]||``).trim());e.length?(this._error=`Enter ${e.join(`, `)}`,this.requestUpdate()):await this._load_models()}async _load_models(){this._loading=!0,this._error=``,this.requestUpdate();try{let e=await nt(this._provider.slug);this._models=e.models||[],this._step=`models`,this._query=``}catch(e){this._error=e.message}finally{this._loading=!1,this.requestUpdate()}}_filtered_models(){let e=this._query.trim().toLowerCase();return e?this._models.filter(t=>t.toLowerCase().includes(e)):this._models}_on_query(e){this._query=e.target.value,this.requestUpdate()}async _select_model(e){if(!this._busy&&e){this._busy=!0,this._error=``,this.requestUpdate();try{await X.configure_provider({provider:this._provider.slug,model:e,api_keys:this._key_values}),this._close()}catch(e){this._error=e.message}finally{this._busy=!1,this.requestUpdate()}}}_on_manual_model(e){if(e.key!==`Enter`||e.isComposing)return;let t=e.target.value.trim();t&&this._select_model(t)}_back(){this._error=``,this._stop_polling(),this._step=`provider`,this._provider=null,this._models=[],this._login=null,this.requestUpdate()}_reset(){this._step=`provider`,this._provider=null,this._key_values={},this._models=[],this._query=``,this._copilot=null,this._login=null,this._error=``,this._busy=!1}_on_backdrop(){this._busy||this._close()}_stop(e){e.stopPropagation()}_close(){this._stop_polling(),this.open=!1,X.close_onboarding(),this.dispatchEvent(new CustomEvent(`close`,{bubbles:!0,composed:!0}))}};customElements.define(`onboarding-dialog`,Xn);var Zn=class extends k{static properties={entry:{attribute:!1}};createRenderRoot(){return this}render(){let e=this.entry,t=e.options||[],n=e.resolving||e.resolved;return C`
      <article
        class="permission-card ${e.resolving?`is-submitting`:``} ${e.resolved?`is-resolved`:``}"
        data-request-id=${e.key}
      >
        <div class="perm-head">
          <span class="perm-icon" aria-hidden="true">${ut}</span>
          <div class="perm-titles">
            <h3 class="perm-title">Permission requested</h3>
            <p class="perm-tool">${e.tool_call.title||`Tool request`}</p>
          </div>
        </div>
        <p class="perm-question">
          ${e.detail||`cecli is asking for permission to continue.`}
        </p>
        <div class="perm-options">
          ${t.length?t.map(t=>C`
                  <button
                    class="perm-option ${Dt(t.kind)} ${e.chosen===String(t.optionId)?`is-chosen`:``}"
                    type="button"
                    data-option-id=${String(t.optionId)}
                    ?disabled=${n}
                    @click=${this._choose}
                  >${t.name||String(t.optionId)}</button>
                `):C`
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
    `}_choose(e){let t=e.currentTarget;this._emit(t.dataset.optionId)}_dismiss(){this._emit(null)}_emit(e){this.entry.resolving||this.entry.resolved||this.dispatchEvent(new CustomEvent(`permission-resolve`,{bubbles:!0,composed:!0,detail:{request_id:this.entry.request_id,option_id:e}}))}};customElements.define(`permission-card`,Zn);var Qn=class extends k{constructor(){super(),this._store=new K(this,J)}createRenderRoot(){return this}render(){let e=this._store.state.permissions;return C`
      <div class="permission-region" ?hidden=${e.length===0}>
        ${j(e,e=>e.key,e=>C`
            <permission-card
              .entry=${e}
              @permission-resolve=${this._on_resolve}
            ></permission-card>
          `)}
      </div>
    `}_on_resolve(e){let{request_id:t,option_id:n}=e.detail;X.resolve_permission(t,n)}};customElements.define(`permission-region`,Qn);var $n=class extends k{constructor(){super(),this._store=new K(this,J),this._workflows_collapsed=!1}createRenderRoot(){return this}render(){let e=this._store.state,t=e.workflows||[];return C`
      <aside class="session-sidebar" aria-label="Workspaces and registries">
        <div class="sidebar-head">
          <span class="sidebar-title">Workspaces</span>
          <button
            class="sidebar-add"
            type="button"
            title="Add workspace"
            ?disabled=${e.sessions.length>=e.max_sessions}
            @click=${this._create}
          >+</button>
        </div>

        <div class="session-tree">
          ${e.sessions.length?j(e.sessions,e=>e.bridgeId,t=>this._render_session(t,e.active_bridge_id)):C`<p class="sidebar-empty">No workspaces yet</p>`}
        </div>

        <div class="sidebar-workflows" data-collapsed=${this._workflows_collapsed}>
          <div class="sidebar-workflows-head" @click=${this._toggle_workflows}>
            <span class="sidebar-title">Workflows</span>
            <span class="sidebar-count">${t.length}</span>
            <button
              type="button"
              class="sidebar-workflows-collapse"
              title=${this._workflows_collapsed?`Expand workflows`:`Collapse workflows`}
              aria-label=${this._workflows_collapsed?`Expand workflows`:`Collapse workflows`}
              aria-expanded=${!this._workflows_collapsed}
              @click=${this._toggle_workflows}
            >${N}</button>
          </div>
          ${t.length?C`
                <ul class="workflow-list">
                  ${j(t,e=>e.name||e.id||String(e),e=>this._render_workflow(e))}
                </ul>
              `:C`<p class="sidebar-empty">No workflows registered</p>`}
        </div>
      </aside>
    `}_toggle_workflows(e){e&&e.stopPropagation(),this._workflows_collapsed=!this._workflows_collapsed,this.requestUpdate()}_render_session(e,t){let n=this._store.state,r=e.bridgeId===t,i=this._activity_for(e,r),a=(n.subagents||[]).filter(e=>!e.removed),o=r&&a.length?a:e.subagents||[];return C`
      <div class="session-node ${r?`is-active`:``}">
        <div class="session-row" @click=${()=>X.switch_session(e.bridgeId)}>
          <span class="status-dot" data-status=${e.status} aria-hidden="true"></span>
          <span class="session-name" title=${e.workspace||``}>${e.title}</span>
          <span class="activity-badge" data-activity=${i}>${i}</span>
          ${e.permissionCount?C`<span class="permission-badge" title="Pending permissions">${e.permissionCount}</span>`:T}
          <button
            class="session-close"
            type="button"
            title=${e.primary?`Primary workspace`:`Remove workspace`}
            ?disabled=${e.busy}
            @click=${t=>this._close(t,e)}
          >×</button>
        </div>

        ${o.length?C`
              <ul class="subagent-tree">
                ${j(o,e=>e.sessionId,t=>this._render_subagent(e,t))}
              </ul>
            `:T}

      </div>
    `}_create(){this.dispatchEvent(new CustomEvent(`add-workspace`,{bubbles:!0,composed:!0}))}_close(e,t){e.stopPropagation(),X.remove_workspace(t.workspace).catch(async e=>{e.message.includes(`Unknown workspace`)?await X.close_session(t.bridgeId).catch(e=>{L(J,e.message,`error`)}):L(J,e.message,`error`)})}_render_workflow(e){let t=e.name||e.id||String(e);return C`
      <li>
        <button
          type="button"
          class="workflow-row"
          title=${e.description||e.title||`Run ${t}`}
          @click=${()=>X.registry_action(`workflows`,`run`,t)}
        >
          <span class="workflow-name">${t}</span>
          <span class="workflow-run">Run</span>
        </button>
      </li>
    `}_select_agent(e,t){X.select_agent(e,t.sessionId)}_render_subagent(e,t){let n=this._store.state,r=(e.bridgeId===n.active_bridge_id?(n.subagents||[]).find(e=>e.sessionId===t.sessionId):null)||t,i=r.running?`running`:r.state||`idle`;return C`
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
    `}_activity_for(e,t){let n=this._store.state;if(!t)return e.activity||e.status||`idle`;let r=(n.subagents||[]).filter(e=>!e.removed);return n.turn_state===`requires_action`?`requires action`:n.busy||r.some(e=>e.running)?`running`:n.activity&&n.activity!==`starting`?n.activity:e.activity||e.status||`idle`}};customElements.define(`session-sidebar`,$n);var er=Re(class extends ze{constructor(e){if(super(e),e.type!==Le.ATTRIBUTE||e.name!==`class`||e.strings?.length>2)throw Error("`classMap()` can only be used in the `class` attribute and must be the only part in the attribute.")}render(e){return` `+Object.keys(e).filter(t=>e[t]).join(` `)+` `}update(e,[t]){if(this.st===void 0){this.st=new Set,e.strings!==void 0&&(this.nt=new Set(e.strings.join(` `).split(/\s/).filter(e=>e!==``)));for(let e in t)t[e]&&!this.nt?.has(e)&&this.st.add(e);return this.render(t)}let n=e.element.classList;for(let e of this.st)e in t||(n.remove(e),this.st.delete(e));for(let e in t){let r=!!t[e];r===this.st.has(e)||this.nt?.has(e)||(r?(n.add(e),this.st.add(e)):(n.remove(e),this.st.delete(e)))}return w}}),tr=class extends k{constructor(){super(),this._store=new K(this,J)}createRenderRoot(){return this}render(){return C`
      <div class="toasts" aria-live="polite" aria-atomic="false">
        ${j(this._store.state.toasts,e=>e.id,e=>C`
            <div
              class=${er({"toast-item":!0,"toast-item--error":e.kind===`error`,"toast-item--info":e.kind!==`error`,"is-visible":e.visible})}
              role="status"
            >${e.message}</div>
          `)}
      </div>
    `}};customElements.define(`toast-stack`,tr);var nr=class extends ze{constructor(e){if(super(e),this.it=T,e.type!==Le.CHILD)throw Error(this.constructor.directiveName+`() can only be used in child bindings`)}render(e){if(e===T||e==null)return this._t=void 0,this.it=e;if(e===w)return e;if(typeof e!=`string`)throw Error(this.constructor.directiveName+`() called with a non-string value`);if(e===this.it)return this._t;this.it=e;let t=[e];return t.raw=t,this._t={_$litType$:this.constructor.resultType,strings:t,values:[]}}};nr.directiveName=`unsafeHTML`,nr.resultType=1;var rr=Re(nr);function ir(e){return String(e??``).replace(/&/g,`&amp;`).replace(/</g,`&lt;`).replace(/>/g,`&gt;`).replace(/"/g,`&quot;`).replace(/'/g,`&#39;`)}function ar(e){let t=ir(e).split(`
`),n=[],r=0;for(;r<t.length;){let e=t[r];if(!e.trim()){r+=1;continue}let i=/^```([\w+#.-]*)\s*$/.exec(e.trim());if(i){let e=i[1]||``,a=[];for(r+=1;r<t.length&&!/^```\s*$/.test(t[r].trim());)a.push(t[r]),r+=1;r<t.length&&(r+=1),n.push(sr(a.join(`
`),e));continue}let a=/^(#{1,3})\s+(.+)$/.exec(e);if(a){let e=a[1].length;n.push(`<h${e}>${Z(a[2])}</h${e}>`),r+=1;continue}if(/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(e)){n.push(`<hr>`),r+=1;continue}if(/^\s*&gt;\s?/.test(e)){let e=[];for(;r<t.length&&/^\s*&gt;\s?/.test(t[r]);)e.push(t[r].replace(/^\s*&gt;\s?/,``)),r+=1;n.push(`<blockquote>${Z(e.join(`
`)).replace(/\n/g,`<br>`)}</blockquote>`);continue}if(/^\s*[-*+]\s+/.test(e)){let e=[];for(;r<t.length&&/^\s*[-*+]\s+/.test(t[r]);)e.push(Z(t[r].replace(/^\s*[-*+]\s+/,``))),r+=1;n.push(`<ul>${e.map(e=>`<li>${e}</li>`).join(``)}</ul>`);continue}if(/^\s*\d+[.)]\s+/.test(e)){let e=[];for(;r<t.length&&/^\s*\d+[.)]\s+/.test(t[r]);)e.push(Z(t[r].replace(/^\s*\d+[.)]\s+/,``))),r+=1;n.push(`<ol>${e.map(e=>`<li>${e}</li>`).join(``)}</ol>`);continue}let o=[];for(;r<t.length&&t[r].trim()&&!or(t[r]);)o.push(t[r]),r+=1;o.length?n.push(`<p>${Z(o.join(`
`)).replace(/\n/g,`<br>`)}</p>`):r+=1}return n.join(``)}function or(e){return/^```/.test(e.trim())||/^#{1,3}\s+/.test(e)||/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(e)||/^\s*&gt;\s?/.test(e)||/^\s*[-*+]\s+/.test(e)||/^\s*\d+[.)]\s+/.test(e)}function sr(e,t){return`<div class="code-block"><div class="code-head"><span class="code-lang">${t?ir(t):`text`}</span><button type="button" class="code-copy" aria-label="Copy code">Copy</button></div><pre><code>${e}</code></pre></div>`}function Z(e){return e.split(/(`[^`\n]+`)/g).map((e,t)=>t%2==1?`<code>${e.slice(1,-1)}</code>`:cr(e)).join(``)}function cr(e){let t=[],n=e.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,(e,n,r)=>(t.push({label:n,url:r}),`\u0000link${t.length-1}\u0000`));return n=lr(n),n=n.replace(/\u0000link(\d+)\u0000/g,(e,n)=>{let r=t[Number(n)];return r?`<a href="${r.url}" target="_blank" rel="noopener noreferrer">${lr(r.label)}</a>`:``}),n}function lr(e){return e.replace(/\*\*([^*]+)\*\*/g,`<strong>$1</strong>`).replace(/__([^_]+)__/g,`<strong>$1</strong>`).replace(/~~([^~]+)~~/g,`<del>$1</del>`).replace(/(^|[^*])\*([^*\n]+)\*/g,`$1<em>$2</em>`).replace(/(^|[^\w])_([^_\n]+)_(?!\w)/g,`$1<em>$2</em>`)}var ur=class extends k{static properties={text:{type:String},streaming:{type:Boolean}};constructor(){super(),this.text=``,this.streaming=!1,this._rendered=``,this._timer=null,this._caret_for=null}createRenderRoot(){return this}willUpdate(e){(e.has(`text`)||e.has(`streaming`))&&(this.streaming?this._schedule_render():this._render_now())}updated(){this.streaming?this._attach_caret():this._remove_caret()}disconnectedCallback(){clearTimeout(this._timer),this._timer=null,super.disconnectedCallback()}render(){return C`
      <div
        class="md ${this.streaming?`is-streaming`:``}"
        @click=${this._on_click}
      >${rr(this._rendered)}</div>
    `}_schedule_render(){this._timer||=setTimeout(()=>{this._timer=null,this._rendered=ar(this.text),this.requestUpdate()},60)}_render_now(){clearTimeout(this._timer),this._timer=null,this._rendered=ar(this.text)}_attach_caret(){if(this._caret_for===this._rendered)return;let e=this.querySelector(`.md`);if(!e)return;let t=document.createElement(`span`);t.className=`stream-caret`,t.setAttribute(`aria-hidden`,`true`);let n=e.lastElementChild;n&&/^(P|LI|H1|H2|H3|BLOCKQUOTE)$/.test(n.tagName)?n.appendChild(t):e.appendChild(t),this._caret_for=this._rendered}_remove_caret(){for(let e of this.querySelectorAll(`.stream-caret`))e.remove();this._caret_for=null}_on_click(e){let t=e.target.closest(`.code-copy`);t&&this._copy_code(t)}async _copy_code(e){let t=e.closest(`.code-block`),n=t?t.querySelector(`code`):null;if(n){try{await navigator.clipboard.writeText(n.textContent)}catch{dr(n.textContent)}fr(e,`Copied`)}}};function dr(e){let t=document.createElement(`textarea`);t.value=e,t.setAttribute(`readonly`,`readonly`),t.style.position=`fixed`,t.style.opacity=`0`,document.body.appendChild(t),t.select();try{document.execCommand(`copy`)}catch{return}finally{t.remove()}}function fr(e,t){let n=e.textContent;e.textContent=t,setTimeout(()=>{e.isConnected&&(e.textContent=n)},1400)}customElements.define(`markdown-view`,ur);var pr=class extends k{static properties={part:{attribute:!1}};createRenderRoot(){return this}render(){let e=this.part.entries||[],t=e.filter(e=>e.status===`completed`).length;return C`
      <article class="plan-card" ?hidden=${e.length===0}>
        <div class="plan-head">
          <span>Plan</span>
          <span class="plan-count badge badge-ghost">${t}/${e.length}</span>
        </div>
        <ul class="plan-list">
          ${e.map(e=>C`
              <li class="plan-item" data-status=${e.status}>
                <span class="plan-mark" aria-hidden="true"></span>
                <span class="plan-text">${e.content}</span>
              </li>
            `)}
        </ul>
      </article>
    `}};customElements.define(`plan-card`,pr);var mr=class extends k{static properties={item:{attribute:!1},agentId:{type:String}};constructor(){super(),this._open_id=null}createRenderRoot(){return this}render(){let e=this.item.parts.filter(e=>e.type===`thought`||e.type===`tool`),t=this.item.parts.filter(e=>e.type!==`thought`&&e.type!==`tool`);return C`
      <div class="msg msg--assistant" data-turn=${this.item.turn}>
        <div class="msg-body">
          ${e.length?C`<div class="assistant-pills">
                ${j(e,e=>e.id,e=>this._render_pill(e))}
              </div>`:T}
          ${this._render_panel(e.find(e=>e.id===this._open_id))}
          ${j(t,e=>e.id,e=>this._render_part(e))}
        </div>
      </div>
    `}_render_pill(e){let t=e.id===this._open_id;if(e.type===`thought`)return C`
        <button
          type="button"
          class="assistant-pill"
          data-active=${t}
          aria-expanded=${String(t)}
          @click=${()=>this._toggle(e.id)}
        >
          <span class="pill-label">Thinking</span>
          <span class="pill-chevron" aria-hidden="true">${N}</span>
        </button>
      `;let n=lt[e.kind]||lt.other;return C`
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
          title=${Et(e.status)}
        ></span>
        <span class="pill-chevron" aria-hidden="true">${N}</span>
      </button>
    `}_render_panel(e){if(!e)return T;if(e.type===`thought`)return C`
        <div class="assistant-pill-panel">
          <div class="pill-panel-body thought-panel-text">${e.text}</div>
        </div>
      `;let t=Ct(e.content_text),n=(e.locations||[]).filter(e=>e&&e.path);return C`
      <div class="assistant-pill-panel">
        <div class="pill-panel-head">
          <span>${Et(e.status)}</span>
          ${n.map(e=>C`<span class="tool-loc" title=${e.path}>
              ${At(e)}
            </span>`)}
        </div>
        ${t?C`<pre><code>${t}</code></pre>`:C`<p class="pill-panel-empty">No output yet.</p>`}
      </div>
    `}_toggle(e){let t=this._open_id!==e;this._open_id=t?e:null,this.requestUpdate(),t&&this.dispatchEvent(new CustomEvent(`transcript-layout`,{bubbles:!0,composed:!0}))}_render_part(e){return e.type===`text`?C`<markdown-view
        .text=${e.text}
        .streaming=${e.streaming}
      ></markdown-view>`:e.type===`plan`?C`<plan-card .part=${e}></plan-card>`:C``}};customElements.define(`assistant-turn`,mr);var hr=class extends k{static properties={item:{attribute:!1}};createRenderRoot(){return this}render(){let e=String(this.item.text||``),t=e.split(`
`).find(e=>e.trim())||``;return C`
      <details class="context-message">
        <summary>
          ${this.item.source?C`<span class="context-message-source" title=${`Sent by ${this.item.source}`}>
                ${this.item.source}
              </span>`:``}
          <span class="context-message-preview">${t}</span>
        </summary>
        <div class="context-message-body">${e}</div>
      </details>
    `}};customElements.define(`context-message`,hr);var gr=`                     ▒▒╗▒▒╗
 ▒▒▒▒▒╗ ▒▒▒▒▒╗ ▒▒▒▒▒╗▒▒║╚═╝
▒▒╔═══╝▒▒▓▓▓▒║▒▒╔═══╝▒▒║▒▒╗
▒▒║    ▒▒╔═══╝▒▒║    ▒▒║▒▒║
╚▒▒▒▒▒╗╚▒▒▒▒▒╗╚▒▒▒▒▒╗▒▒║▒▒║
 ╚════╝ ╚════╝ ╚════╝╚═╝╚═╝`,_r=class extends k{createRenderRoot(){return this}render(){return C`<pre class="cecli-logo" role="img" aria-label="cecli">${gr}</pre>`}};customElements.define(`brand-logo`,_r);var vr=[{prompt:`Explain the structure of this repository and where I should start reading.`,title:`Explain this repo`},{prompt:`Find a likely bug in the current changes and explain how to fix it.`,title:`Find a bug`},{prompt:`Run the test suite and summarise any failures with likely causes.`,title:`Run the tests`}],yr=class extends k{createRenderRoot(){return this}render(){return C`
      <section class="empty-state">
        <brand-logo></brand-logo>
        <h1>What do you need help with?</h1>
        <p>Ask a question, request a change, or start with one of these.</p>
        <div class="examples">
          ${vr.map(e=>C`
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
    `}_on_example(e){let t=e.currentTarget;this.dispatchEvent(new CustomEvent(`example-select`,{bubbles:!0,composed:!0,detail:{prompt:t.dataset.prompt}}))}};customElements.define(`empty-state`,yr);var br=class extends k{static properties={text:{type:String}};constructor(){super(),this.text=``}createRenderRoot(){return this}render(){return C`
      <div class="msg msg--user">
        <div class="bubble">${this.text}</div>
      </div>
    `}};customElements.define(`user-message`,br);var xr=class extends k{constructor(){super(),this._store=new K(this,J),this._observer=null}createRenderRoot(){return this}firstUpdated(){let e=this._transcript();e&&(this._observer=new MutationObserver(()=>this._maybe_autoscroll()),this._observer.observe(e,{childList:!0,subtree:!0,characterData:!0}),this._resize_observer=new ResizeObserver(()=>this._maybe_autoscroll()),this._resize_observer.observe(e))}disconnectedCallback(){this._observer&&this._observer.disconnect(),this._observer=null,this._resize_observer&&this._resize_observer.disconnect(),this._resize_observer=null,this._scroll_timer&&clearTimeout(this._scroll_timer),this._scroll_timer=null,super.disconnectedCallback()}updated(){this._maybe_autoscroll(),queueMicrotask(()=>this._maybe_autoscroll()),this._scroll_timer&&clearTimeout(this._scroll_timer),this._scroll_timer=setTimeout(()=>{this._scroll_timer=null,this._maybe_autoscroll()},0)}render(){let e=this._store.state,t=q.visible_transcript(e);return C`
      <div
        class="transcript"
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        tabindex="0"
        @scroll=${this._on_scroll}
        @transcript-layout=${this._maybe_autoscroll}
      >
        ${q.visible_busy(e)&&t.length===0?C`<p class="history-note">
              This turn is running in the background; earlier transcript history is not
              replayed after a reload.
            </p>`:T}
        <empty-state
          ?hidden=${q.has_transcript(e)||q.visible_busy(e)}
          @example-select=${this._on_example}
        ></empty-state>
        ${j(t,e=>e.id,t=>t.type===`user`?C`<user-message .text=${t.text}></user-message>`:t.type===`context`?C`<context-message .item=${t}></context-message>`:C`<assistant-turn
                  .item=${t}
                  .agentId=${e.active_agent_session_id}
                ></assistant-turn>`)}
      </div>
    `}_transcript(){return this.querySelector(`.transcript`)}_near_bottom(){let e=this._transcript();return!e||e.scrollHeight-e.scrollTop-e.clientHeight<80}_scroll_to_bottom(e){let t=this._transcript();t&&t.scrollTo({top:t.scrollHeight,behavior:e?`smooth`:`auto`})}_maybe_autoscroll(){this._store.state.auto_scroll&&this._scroll_to_bottom(!1)}_on_scroll(){let e=this._near_bottom();this._store.state.auto_scroll!==e&&X.set_auto_scroll(e)}_on_example(e){X.fill_composer(e.detail&&e.detail.prompt)}};customElements.define(`transcript-view`,xr);var Sr=`/api/background`;async function Cr(e){let t=await Er(e,{action:`list`});return(Array.isArray(t?.commands)?t.commands:[]).map(Or).filter(Boolean)}async function wr(e,t){let n=await Er(e,{action:`output`,key:t});return{output:typeof n?.output==`string`?n.output:``,command:Or(n?.command)}}function Tr(){if(typeof AbortSignal<`u`&&typeof AbortSignal.timeout==`function`)return AbortSignal.timeout(8e3)}async function Er(e,t){let n;try{n=await fetch(Sr,{method:`POST`,headers:{"Content-Type":`application/json`},signal:Tr(),body:JSON.stringify({bridgeId:e,...t})})}catch(e){throw Dr(e?.message||`Background service unreachable`,0)}let r=null;try{r=await n.json()}catch{r=null}if(!n.ok||r?.ok===!1)throw Dr(r?.error||r?.message||`Background request failed (${n.status})`,n.status);return r||{}}function Dr(e,t){let n=Error(e);return n.status=t,n.unavailable=t===0||t===404||t===409||t===503,n}function Or(e){if(!e||typeof e!=`object`)return null;let t=e.key??e.id;return t?{key:String(t),command:typeof e.command==`string`?e.command:``,running:!!e.running,persist:!!e.persist,continued_in_background:!!(e.continuedInBackground??e.continued_in_background),buffer_size:kr(e.bufferSize??e.buffer_size),pages:kr(e.pages),total_chars:Ar(e.totalChars??e.total_chars),start_time:e.startTime??e.start_time??null,end_time:e.endTime??e.end_time??null,duration:typeof e.duration==`number`?e.duration:null}:null}function kr(e){return typeof e==`number`&&Number.isFinite(e)?e:0}function Ar(e){return typeof e==`number`&&Number.isFinite(e)?e:null}var jr=1e3,Mr=500,Nr=20,Pr=new Set(`bash.sh.zsh.fish.dash.node.nodejs.deno.bun.python.python3.py.ruby.perl.php.uv.npx.npm.pnpm.yarn.cargo.go.java.dotnet.poetry.pipenv`.split(`.`)),Fr=class extends k{constructor(){super(),this._store=new K(this,J),this._commands=[],this._selected_key=null,this._output=``,this._follow=!0,this._collapsed=!1,this._list_error=``,this._output_error=``,this._bridge_id=null,this._bridge_dirty=!1,this._list_timer=null,this._list_inflight=!1,this._output_inflight_key=null,this._output_token=0,this._output_signature=``,this._scroll_to_bottom_pending=!1,this._pending_scroll_top=null,this._on_visibility_change=this._handle_visibility_change.bind(this)}createRenderRoot(){return this}connectedCallback(){super.connectedCallback(),document.addEventListener(`visibilitychange`,this._on_visibility_change),this.hasUpdated&&(this._sync_store_context(),this._bridge_dirty&&this.requestUpdate(),this._sync_polling(),this._tick())}disconnectedCallback(){document.removeEventListener(`visibilitychange`,this._on_visibility_change),this._stop_polling(),super.disconnectedCallback()}willUpdate(){this._sync_store_context()}updated(){this.toggleAttribute(`data-collapsed`,this._collapsed),this._sync_polling(),this._bridge_dirty&&(this._bridge_dirty=!1,this._tick()),this._apply_scroll()}render(){let e=this._store.state,t=this._commands,n=this._selected_command(),r=this._list_error||this._output_error;return C`
      <section
        class="background-panel"
        aria-label="Background commands"
      >
        <header class="background-header" @click=${this._toggle_collapsed}>
          <span class="background-heading">Background</span>
          <span class="background-count" data-state=${this._header_state(e)}>${this._count_label(e)}</span>
          <button
            class="background-follow"
            type="button"
            data-active=${this._follow}
            aria-pressed=${this._follow}
            title=${this._follow?`Following output`:`Follow output`}
            @click=${e=>{e.stopPropagation(),this._toggle_follow()}}
          >
            Follow
          </button>
          <button
            type="button"
            class="background-collapse"
            title=${this._collapsed?`Expand background`:`Collapse background`}
            aria-label=${this._collapsed?`Expand background`:`Collapse background`}
            aria-expanded=${!this._collapsed}
            @click=${this._toggle_collapsed}
          >${N}</button>
        </header>

        ${r?C`<p class="background-note" role="status">${r}</p>`:T}
        ${t.length===0?C`<p class="background-empty">No active background commands.</p>`:C`
              <div class="background-tabs" role="tablist" aria-label="Background command tabs">
                ${j(t,e=>e.key,e=>C`
                    <button
                      class="background-tab"
                      type="button"
                      role="tab"
                      data-active=${e.key===this._selected_key}
                      aria-selected=${e.key===this._selected_key}
                      title=${e.command||e.key}
                      @click=${()=>this._select(e.key)}
                    >
                      ${Lr(e)}
                    </button>
                  `)}
              </div>
              <div class="background-command-line" title=${n?.command||``}>
                ${n?.command||``}
              </div>
              <pre
                class="background-output"
                aria-label="Background command output"
                tabindex="0"
                @scroll=${this._on_output_scroll}
              >${this._visible_output()}</pre>
            `}
      </section>
    `}_select(e){e!==this._selected_key&&(this._selected_key=e,this._output=``,this._output_signature=``,this._output_error=``,this._pending_scroll_top=null,this._scroll_to_bottom_pending=this._follow,this._output_inflight_key=null,this._output_token+=1,this.requestUpdate(),this._maybe_fetch_output())}_toggle_collapsed(e){e&&e.stopPropagation(),this._collapsed=!this._collapsed,this.requestUpdate()}_toggle_follow(){if(this._follow=!this._follow,this._follow)this._scroll_to_bottom_pending=!0,this._pending_scroll_top=null;else{let e=this._output_element();this._scroll_to_bottom_pending=!1,this._pending_scroll_top=e?e.scrollTop:null}this.requestUpdate()}async _tick(){if(!this._bridge_id||!this._is_panel_visible()||this._list_inflight)return;let e=this._bridge_id;this._list_inflight=!0;try{let t=await Cr(e);if(e!==this._bridge_id)return;this._list_error=``,this._apply_commands(t)}catch(t){if(e!==this._bridge_id)return;this._set_error(`list`,t);return}finally{this._list_inflight=!1}await this._maybe_fetch_output()}_sync_polling(){this._bridge_id&&this.isConnected&&!document.hidden?this._list_timer===null&&(this._list_timer=setInterval(()=>this._tick(),jr)):this._stop_polling()}_sync_store_context(){let e=this._store.state,t=e.connected&&(J.active_bridge_id||e.bridge_id)||null;t!==this._bridge_id&&(this._bridge_id=t,this._bridge_dirty=!0,this._reset_view())}_apply_commands(e){let t=e.filter(Ir),n=this._selected_key,r=t.some(e=>e.key===n);this._commands=t,r||(this._selected_key=t[0]?.key||null,this._selected_key!==n&&(this._output=``,this._output_signature=``,this._output_error=``,this._output_inflight_key=null,this._output_token+=1,this._pending_scroll_top=null,this._scroll_to_bottom_pending=this._follow)),this.requestUpdate()}async _maybe_fetch_output(){let e=this._selected_command();if(!e||!this._bridge_id||!this._is_panel_visible()||this._output_inflight_key===e.key)return;let t=e.total_chars??e.buffer_size,n=`${e.key}:${t}`;n!==this._output_signature&&await this._fetch_output(e.key,n)}async _fetch_output(e,t){let n=this._bridge_id,r=++this._output_token;this._output_inflight_key=e;try{let i=await wr(n,e);if(r!==this._output_token||e!==this._selected_key)return;this._output_error=``,this._output_signature=t,this._set_output(i.output)}catch(e){if(r!==this._output_token)return;this._set_error(`output`,e)}finally{r===this._output_token&&this._output_inflight_key===e&&(this._output_inflight_key=null)}}_set_output(e){let t=this._output_element();t&&!this._follow&&(this._pending_scroll_top=t.scrollTop),this._output=e,this._scroll_to_bottom_pending=this._follow,this.requestUpdate()}_reset_view(){this._commands=[],this._selected_key=null,this._output=``,this._output_signature=``,this._list_error=``,this._output_error=``,this._output_inflight_key=null,this._output_token+=1,this._scroll_to_bottom_pending=!1,this._pending_scroll_top=null}_stop_polling(){this._list_timer!==null&&(clearInterval(this._list_timer),this._list_timer=null)}_handle_visibility_change(){document.hidden?this._stop_polling():(this._sync_polling(),this._tick())}_set_error(e,t){let n=zr(t);if(e===`list`){if(this._list_error===n)return;this._list_error=n}else{if(this._output_error===n)return;this._output_error=n}this.requestUpdate()}_selected_command(){return this._commands.find(e=>e.key===this._selected_key)||null}_visible_output(){let e=this._output.split(`
`);return e.length<=Mr?this._output:e.slice(-500).join(`
`)}_output_element(){return this.querySelector(`.background-output`)}_on_output_scroll(e){let t=e.currentTarget;t&&this._follow&&(t.scrollHeight-t.scrollTop-t.clientHeight<=12||(this._follow=!1,this._scroll_to_bottom_pending=!1,this.requestUpdate()))}_apply_scroll(){let e=this._output_element();e&&(this._scroll_to_bottom_pending&&this._follow?(e.scrollTop=e.scrollHeight,this._scroll_to_bottom_pending=!1,this._pending_scroll_top=null):this._pending_scroll_top!==null&&(e.scrollTop=this._pending_scroll_top,this._pending_scroll_top=null))}_is_panel_visible(){return!this.isConnected||this.hidden||document.hidden?!1:typeof this.checkVisibility==`function`?this.checkVisibility({checkOpacity:!1,checkVisibilityCSS:!0}):this.getClientRects().length>0}_count_label(e){return e.connected?this._commands.length?`${this._commands.length} running`:`idle`:`offline`}_header_state(e){return e.connected?this._list_error||this._output_error?`unavailable`:this._commands.length?`running`:`idle`:`offline`}};function Ir(e){return!(!e.running||e.persist&&!e.continued_in_background)}function Lr(e){let t=(e.command||``).trim().split(/\s+/).filter(Boolean),n=t[0]||e.key;Pr.has(Rr(n))&&t[1]&&!t[1].startsWith(`-`)&&(n=t[1]);let r=Rr(n)||e.key;return r.length>Nr?`${r.slice(0,19)}\u2026`:r}function Rr(e){let t=String(e).replace(/[\\/]+$/,``),n=t.split(/[\\/]/);return n[n.length-1]||t}function zr(e){return e?.status===409?`Background commands unavailable for this session.`:e?.unavailable?`Background service unavailable.`:e?.message||`Background request failed.`}customElements.define(`background-panel`,Fr);var Br={"Content-Type":`application/json`};function Q(e,t,n=1e4){return Zr(e,{method:`POST`,headers:Br,body:JSON.stringify(t===void 0?{}:t),timeout_ms:n})}function Vr(){return Zr(`/api/browser/state`,{headers:{Accept:`application/json`}})}function Hr(){return Q(`/api/browser/start`,{},45e3)}function Ur(e){return Q(`/api/browser/open`,{url:e})}function Wr(e){return Q(`/api/browser/action`,{action:e})}function Gr(e=null){return Q(`/api/browser/tab/new`,e?{url:e}:{})}function Kr(e){return Q(`/api/browser/tab/close`,{tabId:e})}function qr(e){return Q(`/api/browser/tab`,{tabId:e})}function Jr(e,t,n){return Q(`/api/browser/viewport`,{width:e,height:t,dpr:n})}function Yr(e){return Q(`/api/browser/input`,{event:e})}function Xr(){return new EventSource(`/api/browser/stream`)}async function Zr(e,t){let n,{timeout_ms:r=1e4,...i}=t;!i.signal&&typeof AbortSignal<`u`&&typeof AbortSignal.timeout==`function`&&(i.signal=AbortSignal.timeout(r));try{n=await fetch(e,i)}catch(e){let t=Error(`Network error: ${e.message}`);throw t.status=0,t}let a=null;try{a=await n.json()}catch{a=null}if(!n.ok||a&&a.ok===!1){let e=Error(a&&(a.error||a.message)||`Request failed (${n.status})`);throw e.status=n.status,e.data=a,e}return a}var Qr=new Set([`Enter`,`Backspace`,`Delete`,`Tab`,`Escape`,`ArrowLeft`,`ArrowRight`,`ArrowUp`,`ArrowDown`,`Home`,`End`,`PageUp`,`PageDown`,`Insert`]),$r=700,ei=8e3,ti=32,ni=32,ri=4,ii=1920,ai=1080,oi=.5,si=3,ci=1.2,li=C`
  <svg
    width="22"
    height="22"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <circle cx="12" cy="12" r="9"></circle>
    <path d="M3 12h18"></path>
    <path d="M12 3c2.7 2.4 4.2 5.4 4.2 9s-1.5 6.6-4.2 9c-2.7-2.4-4.2-5.4-4.2-9S9.3 5.4 12 3z"></path>
  </svg>
`,ui=class extends k{constructor(){super(),this._available=null,this._running=!1,this._browser=``,this._executable=``,this._profile=``,this._port=null,this._url=``,this._title=``,this._error=``,this._viewport={width:0,height:0,dpr:1},this._starting=!1,this._navigating=!1,this._stream_status=`idle`,this._url_draft=``,this._tabs=[],this._active_tab_id=null,this._zoom=1,this._zoom_pending=!1,this._zoom_anchor=null,this._switching_tab=!1,this._creating_tab=!1,this._collapsed=!1,this._scroll={x:0,y:0,maxX:0,maxY:0},this._scroll_known=!1,this._canvas=null,this._viewport_el=null,this._stage_el=null,this._url_input=null,this._last_bitmap=null,this._frame_meta=null,this._frame_rect=null,this._frame_ready=!1,this._pending_frame=null,this._decoding=!1,this._redraw_scheduled=!1,this._disconnected=!1,this._stream=null,this._reconnect_timer=null,this._reconnect_delay=$r,this._resize_observer=null,this._viewport_send_timer=null,this._last_viewport_key=``,this._window_resize_bound=!1,this._wheel_bound=!1,this._pointer_pressed=!1,this._pointer_button=0,this._last_click_time=0,this._last_click_button=-1,this._click_count=0,this._held_keys=new Map,this._input_queue=[],this._input_flushing=!1,this._navigating_timer=null,this._on_wheel=this._on_wheel.bind(this),this._on_viewport_resize=this._on_viewport_resize.bind(this),this._on_visibility_change=this._on_visibility_change.bind(this)}createRenderRoot(){return this}connectedCallback(){super.connectedCallback(),document.addEventListener(`visibilitychange`,this._on_visibility_change),this._fetch_state(),document.hidden||this._connect_stream(),this.hasUpdated&&this.updateComplete.then(()=>{this.isConnected&&(this._cache_elements(),this._bind_wheel(),this._setup_resize_observer(),this._queue_viewport_send(0))})}disconnectedCallback(){this._disconnected=!0,document.removeEventListener(`visibilitychange`,this._on_visibility_change),this._close_stream(),clearTimeout(this._reconnect_timer),this._reconnect_timer=null,clearTimeout(this._viewport_send_timer),this._viewport_send_timer=null,clearTimeout(this._navigating_timer),this._navigating_timer=null,this._resize_observer&&=(this._resize_observer.disconnect(),null),this._window_resize_bound&&=(window.removeEventListener(`resize`,this._on_viewport_resize),!1),this._canvas&&this._wheel_bound&&(this._canvas.removeEventListener(`wheel`,this._on_wheel),this._wheel_bound=!1),this._held_keys.clear(),this._drop_frame(),super.disconnectedCallback()}updated(){if(this.toggleAttribute(`data-collapsed`,this._collapsed),this._cache_elements(),this._bind_wheel(),this._setup_resize_observer(),this._apply_zoom(),this._zoom_pending){let e=this._zoom_anchor;this._zoom_pending=!1,requestAnimationFrame(()=>this._after_zoom(e))}}render(){let e=this._running,t=this._status();return C`
      <section class="browser-panel" aria-label="Browser">
        <header class="browser-head" @click=${this._toggle_collapsed}>
          <div class="browser-head-title">
            <span class="browser-title">Browser</span>
          </div>
          <span
            class="browser-status-text"
            data-state=${t.state}
            title=${this._status_detail()}
          >${t.label}</span>
          <button
            type="button"
            class="browser-collapse"
            title=${this._collapsed?`Expand browser`:`Collapse browser`}
            aria-label=${this._collapsed?`Expand browser`:`Collapse browser`}
            aria-expanded=${!this._collapsed}
            @click=${this._toggle_collapsed}
          >${N}</button>
        </header>

        <div class="browser-toolbar" role="toolbar" aria-label="Browser controls">
          <button
            type="button"
            class="browser-icon-btn"
            title="Back"
            aria-label="Back"
            ?disabled=${!e}
            @click=${()=>this._action(`back`)}
          >&#8592;</button>
          <button
            type="button"
            class="browser-icon-btn"
            title="Forward"
            aria-label="Forward"
            ?disabled=${!e}
            @click=${()=>this._action(`forward`)}
          >&#8594;</button>
          <button
            type="button"
            class="browser-icon-btn"
            title=${this._navigating?`Stop loading`:`Reload`}
            aria-label=${this._navigating?`Stop loading`:`Reload`}
            ?disabled=${!e}
            @click=${()=>this._action(this._navigating?`stop`:`reload`)}
          >${this._navigating?`■`:`⟳`}</button>
          <input
            class="browser-url"
            type="text"
            .value=${this._url_draft}
            placeholder="Search Google or enter address"
            spellcheck="false"
            autocomplete="off"
            aria-label="Browser address"
            ?disabled=${!e}
            @input=${this._on_url_input}
            @keydown=${this._on_url_keydown}
          />
          <button
            type="button"
            class="browser-go"
            ?disabled=${!e}
            @click=${this._open_url}
          >Go</button>
        </div>

        ${this._error?C`
              <div class="browser-error" role="alert">
                <span class="browser-error-text">${this._error}</span>
                <button
                  type="button"
                  class="browser-error-dismiss"
                  title="Dismiss"
                  aria-label="Dismiss error"
                  @click=${this._dismiss_error}
                >\u00d7</button>
              </div>
            `:T}
        ${this._render_tabs()}

        <div class="browser-viewport">
          <div class="browser-stage">
          <canvas
            class="browser-canvas"
            tabindex="0"
            aria-label="Browser page viewport"
            @pointerdown=${this._on_pointerdown}
            @pointermove=${this._on_pointermove}
            @pointerup=${this._on_pointerup}
            @pointercancel=${this._on_pointercancel}
            @contextmenu=${this._on_contextmenu}
            @keydown=${this._on_canvas_keydown}
            @keyup=${this._on_canvas_keyup}
            @paste=${this._on_paste}
            @blur=${this._on_canvas_blur}
          ></canvas>
          </div>
          ${this._render_overlay()}
        </div>

        <footer class="browser-foot">
          <span class="browser-foot-url" title=${this._url}>${this._title||this._url||`No page loaded`}</span>
          <span class="browser-foot-meta">
            <span class="browser-zoom" role="group" aria-label="Canvas zoom">
              <button
                type="button"
                class="browser-zoom-btn"
                title="Zoom out canvas"
                aria-label="Zoom out canvas"
                ?disabled=${!this._running||this._zoom<=oi}
                @click=${this._zoom_out}
              >\u2212</button>
              <button
                type="button"
                class="browser-zoom-value"
                title="Reset canvas zoom"
                aria-label="Reset canvas zoom"
                @click=${this._reset_zoom}
              >${Math.round(this._zoom*100)}%</button>
              <button
                type="button"
                class="browser-zoom-btn"
                title="Zoom in canvas"
                aria-label="Zoom in canvas"
                ?disabled=${!this._running||this._zoom>=si}
                @click=${this._zoom_in}
              >+</button>
            </span>
            <span class="browser-viewport-size">${this._viewport_label()}</span>
          </span>
        </footer>
      </section>
    `}_render_overlay(){return this._running&&this._frame_ready?T:this._starting?this._empty_state({icon:C`<span class="browser-spinner"></span>`,title:`Starting browser…`,description:`Launching the local browser backend.`}):this._available===!1?this._empty_state({icon:li,title:`Browser unavailable`,description:C`
          Chrome or Edge was not found. Install one, or set
          <code>CECLI_BROWSER_BIN</code> to the executable path and restart the bridge.
          ${this._executable?C`<span class="browser-empty-hint">Last checked: <code>${this._executable}</code></span>`:T}
        `,actions:C`
          <button type="button" class="browser-btn" @click=${this._retry}>Retry</button>
          <button
            type="button"
            class="browser-btn browser-btn--primary"
            ?disabled=${this._starting}
            @click=${this._start}
          >Start browser</button>
        `}):this._available===null?this._error?this._empty_state({icon:li,title:`Browser backend unavailable`,description:`The browser service did not respond. Check that the desktop bridge is running.`,actions:C`
            <button type="button" class="browser-btn" @click=${this._retry}>Retry</button>
          `}):this._empty_state({icon:C`<span class="browser-spinner"></span>`,title:`Checking for a browser…`,description:`Contacting the desktop bridge.`}):this._running?this._empty_state({icon:C`<span class="browser-spinner"></span>`,title:`Waiting for the first frame…`,description:this._url?`Loading ${this._url}.`:`The browser is running.`}):this._empty_state({icon:li,title:`Browser is not running`,description:`Start a local browser to preview and interact with pages inside cecli.`,actions:C`
          <button
            type="button"
            class="browser-btn browser-btn--primary"
            ?disabled=${this._starting}
            @click=${this._start}
          >Start browser</button>
        `})}_empty_state({icon:e,title:t,description:n,actions:r}){return C`
      <div class="browser-empty" role="status">
        <span class="browser-empty-icon" aria-hidden="true">${e}</span>
        <h3 class="browser-empty-title">${t}</h3>
        <p class="browser-empty-text">${n}</p>
        ${r?C`<div class="browser-empty-actions">${r}</div>`:T}
      </div>
    `}_status(){return this._starting?{state:`busy`,label:`Starting…`}:this._stream_status===`retrying`?{state:this._running?`live`:`off`,label:`Reconnecting…`}:this._running?{state:`live`,label:this._navigating?`Loading…`:`Live`}:this._available===!1?{state:`off`,label:`Unavailable`}:this._available===null?{state:`busy`,label:`Checking…`}:{state:`ready`,label:`Ready`}}_status_detail(){let e=[];return this._browser&&e.push(this._browser),this._port&&e.push(`port ${this._port}`),this._profile&&e.push(this._profile),e.join(` · `)}_viewport_label(){let e=this._viewport;if(!e||!e.width||!e.height)return this._port?`port ${this._port}`:``;let t=e.dpr&&e.dpr!==1?` @${e.dpr}x`:``;return`${Math.round(e.width)}\u00d7${Math.round(e.height)}${t}`}_render_tabs(){return this._running?C`
      <div class="browser-tabs" role="tablist" aria-label="Browser tabs">
        ${this._tabs.map(e=>C`
            <div
              class="browser-tab"
              role="tab"
              data-active=${e.id===this._active_tab_id}
              aria-selected=${e.id===this._active_tab_id}
              title=${e.title||e.url||e.id}
            >
              <button
                type="button"
                class="browser-tab-label"
                ?disabled=${this._switching_tab}
                @click=${()=>this._select_tab(e.id)}
              >${di(e)}</button>
              <button
                type="button"
                class="browser-tab-close"
                title="Close tab"
                aria-label="Close tab"
                ?disabled=${this._switching_tab}
                @click=${t=>this._close_tab(e.id,t)}
              >\u00d7</button>
            </div>
          `)}
        <button
          type="button"
          class="browser-tab-new"
          title="New tab"
          aria-label="New tab"
          ?disabled=${this._creating_tab}
          @click=${this._new_tab}
        >+</button>
      </div>
    `:T}_toggle_collapsed(e){e&&e.stopPropagation(),this._collapsed=!this._collapsed,this.requestUpdate()}async _new_tab(){if(!this._creating_tab){this._creating_tab=!0,this._error=``,this.requestUpdate();try{let e=await Gr();e&&typeof e==`object`&&this._apply_state(e)}catch(e){this._set_error(e)}finally{this._creating_tab=!1,this.requestUpdate()}}}async _close_tab(e,t){if(t?.stopPropagation(),e&&!this._switching_tab){this._switching_tab=!0,this._error=``,this.requestUpdate();try{let t=await Kr(e);t&&typeof t==`object`&&this._apply_state(t)}catch(e){this._set_error(e)}finally{this._switching_tab=!1,this.requestUpdate()}}}async _select_tab(e){if(e&&!this._switching_tab&&e!==this._active_tab_id){this._switching_tab=!0,this._error=``,this.requestUpdate();try{let t=await qr(e);t&&typeof t==`object`&&this._apply_state(t)}catch(e){this._set_error(e)}finally{this._switching_tab=!1,this.requestUpdate()}}}_zoom_in(){this._set_zoom(this._zoom*ci)}_zoom_out(){this._set_zoom(this._zoom/ci)}_reset_zoom(){this._set_zoom(1)}_set_zoom(e,t=null){let n=Number($(e,oi,si).toFixed(2));n!==this._zoom&&(this._zoom_anchor=t||this._center_anchor(),this._zoom=n,this._zoom_pending=!0,this.requestUpdate())}_center_anchor(){let e=this._stage_el,t=this._viewport_el;return!e||!t||!e.offsetWidth||!e.offsetHeight?null:{x:$((t.scrollLeft+t.clientWidth/2-e.offsetLeft)/e.offsetWidth,0,1),y:$((t.scrollTop+t.clientHeight/2-e.offsetTop)/e.offsetHeight,0,1)}}_pointer_anchor(e){let t=this._stage_el;if(!t)return null;let n=t.getBoundingClientRect();return{x:$((e.clientX-n.left)/Math.max(n.width,1),0,1),y:$((e.clientY-n.top)/Math.max(n.height,1),0,1)}}_apply_zoom(){let e=this._stage_el;if(!e)return;let t=`${(this._zoom*100).toFixed(2)}%`,n=`${(this._zoom*100).toFixed(2)}%`;e.style.width!==t&&(e.style.width=t),e.style.height!==n&&(e.style.height=n)}_after_zoom(e){if(this._disconnected)return;let t=this._stage_el,n=this._viewport_el;t&&n&&e&&(n.scrollLeft=Math.max(0,t.offsetLeft+e.x*t.offsetWidth-n.clientWidth/2),n.scrollTop=Math.max(0,t.offsetTop+e.y*t.offsetHeight-n.clientHeight/2)),this._last_bitmap&&this._draw_bitmap(this._last_bitmap)}_on_url_input(e){this._url_draft=e.target.value}_on_url_keydown(e){e.key===`Enter`?(e.preventDefault(),this._open_url()):e.key===`Escape`&&e.stopPropagation()}async _open_url(){let e=fi(this._url_draft);if(!e)this._url_input&&this._url_input.focus();else{this._url_draft=e,this._set_navigating(!0),this._error=``,this.requestUpdate();try{let t=await Ur(e);t&&typeof t==`object`&&this._apply_state(t)}catch(e){this._set_navigating(!1),this._set_error(e)}}}async _action(e){if(this._running){e===`stop`?this._set_navigating(!1):this._set_navigating(!0);try{let t=await Wr(e);t&&typeof t==`object`&&this._apply_state(t)}catch(e){this._set_navigating(!1),this._set_error(e)}}}async _start(){if(!this._starting){this._starting=!0,this._error=``,this.requestUpdate();try{let e=await Hr();e&&typeof e==`object`&&this._apply_state(e),e&&`running`in e||(this._running=!0),this._last_viewport_key=``,this._queue_viewport_send(0)}catch(e){this._set_error(e)}finally{this._starting=!1,this.requestUpdate()}}}_retry(){this._available=null,this._error=``,this.requestUpdate(),this._connect_stream(),this._fetch_state()}_dismiss_error(){this._error=``,this.requestUpdate()}async _fetch_state(){try{let e=await Vr();this._apply_state(e)}catch(e){this._error=e&&e.message?e.message:String(e),this.requestUpdate()}}_apply_state(e){if(!e||typeof e!=`object`)return;let t=this._running;typeof e.available==`boolean`&&(this._available=e.available),typeof e.running==`boolean`&&(this._running=e.running),`browser`in e&&(this._browser=typeof e.browser==`string`?e.browser:``),`executable`in e&&(this._executable=typeof e.executable==`string`?e.executable:``),`profile`in e&&(this._profile=typeof e.profile==`string`?e.profile:``),`port`in e&&(this._port=e.port??null),`title`in e&&(this._title=typeof e.title==`string`?e.title:``),`url`in e&&(this._url=typeof e.url==`string`?e.url:``,this._url_input!==document.activeElement&&(this._url_draft=this._url)),Array.isArray(e.tabs)&&(this._tabs=e.tabs.filter(e=>e&&typeof e.id==`string`).map(e=>({id:e.id,title:typeof e.title==`string`?e.title:``,url:typeof e.url==`string`?e.url:``,active:!!e.active}))),e.scroll&&typeof e.scroll==`object`?(this._scroll={x:Number(e.scroll.x)||0,y:Number(e.scroll.y)||0,maxX:Number(e.scroll.maxX)||0,maxY:Number(e.scroll.maxY)||0},this._scroll_known=!0):e.scroll===null&&(this._scroll_known=!1),`activeTabId`in e&&(this._active_tab_id=typeof e.activeTabId==`string`?e.activeTabId:null),e.viewport&&typeof e.viewport==`object`&&(this._viewport={width:Number(e.viewport.width)||0,height:Number(e.viewport.height)||0,dpr:Number(e.viewport.dpr)||1}),e.error?this._error=String(e.error):e.ok!==!1&&(this._error=``),this._running&&!t&&(this._last_viewport_key=``,this._queue_viewport_send(0)),!this._running&&t&&(this._clear_frame(),this._set_navigating(!1),this._tabs=[],this._active_tab_id=null),this.requestUpdate()}_connect_stream(){if(this._close_stream(),clearTimeout(this._reconnect_timer),this._reconnect_timer=null,this._disconnected)return;this._stream_status=`connecting`,this.requestUpdate();let e;try{e=Xr()}catch{this._stream_status=`retrying`,this.requestUpdate(),this._schedule_reconnect();return}this._stream=e,e.onopen=()=>{this._last_viewport_key=``,this._reconnect_delay=$r,this._stream_status=`open`,this.requestUpdate(),this._fetch_state(),this._queue_viewport_send(0)},e.onmessage=e=>this._handle_stream_message(e),e.onerror=()=>{this._stream===e&&(this._close_stream(),this._stream_status=`retrying`,this.requestUpdate(),this._schedule_reconnect())}}_close_stream(){if(this._stream){try{this._stream.close()}catch{}this._stream=null}}_schedule_reconnect(){if(this._disconnected||this._reconnect_timer)return;let e=Math.round(this._reconnect_delay*(.8+Math.random()*.4));this._reconnect_delay=Math.min(Math.round(this._reconnect_delay*1.7),ei),this._reconnect_timer=setTimeout(()=>{this._reconnect_timer=null,this._connect_stream()},e)}_on_visibility_change(){document.hidden?(this._close_stream(),clearTimeout(this._reconnect_timer),this._reconnect_timer=null,this._stream_status=`paused`,this.requestUpdate()):(this._stream||this._connect_stream(),this._fetch_state())}_handle_stream_message(e){let t;try{t=JSON.parse(e.data)}catch{return}t&&typeof t==`object`&&(t.type===`state`?this._apply_state(t.state):t.type===`frame`?this._handle_frame(t):t.type===`error`&&this._set_error(t.message||`Browser stream error`))}_handle_frame(e){if(!e.data||document.hidden||!this.isConnected||typeof this.checkVisibility==`function`&&!this.checkVisibility({checkVisibilityCSS:!0}))return;let t=e.meta&&typeof e.meta==`object`?e.meta:{};this._enqueue_frame(e.data,t)}_enqueue_frame(e,t){this._pending_frame={data:e,meta:t},this._decoding||this._decode_next()}async _decode_next(){let e=this._pending_frame;if(e){this._pending_frame=null,this._decoding=!0;try{let t=await this._decode_frame(e.data);if(this._disconnected||!this._running){hi(t);return}this._frame_meta=e.meta,this._last_bitmap&&hi(this._last_bitmap),this._last_bitmap=t;let n=this._frame_ready,r=this._navigating;this._frame_ready=!0,this._navigating&&(this._navigating=!1,clearTimeout(this._navigating_timer),this._navigating_timer=null),this._draw_bitmap(t),(!n||r)&&this.requestUpdate()}catch{}finally{this._decoding=!1,this._pending_frame&&this._decode_next()}}}async _decode_frame(e){let t=pi(e);if(typeof createImageBitmap==`function`)try{return await createImageBitmap(t)}catch{}return mi(t)}_draw_bitmap(e){let t=this._canvas_context();if(!t)return;let{ctx:n,css_width:r,css_height:i,dpr:a}=t;n.setTransform(a,0,0,a,0,0),n.fillStyle=`#14161b`,n.fillRect(0,0,r,i);let o=e.width||e.naturalWidth||0,s=e.height||e.naturalHeight||0;if(!o||!s){this._frame_rect=null;return}let c=Math.min(r/o,i/s),l=o*c,u=s*c,d=(r-l)/2,f=(i-u)/2;n.imageSmoothingEnabled=!0,n.imageSmoothingQuality=`high`,n.drawImage(e,d,f,l,u),this._frame_rect={x:d,y:f,width:l,height:u,source_width:o,source_height:s}}_clear_frame(){this._drop_frame(),this._clear_canvas()}_drop_frame(){this._pending_frame=null,this._frame_meta=null,this._frame_rect=null,this._frame_ready=!1,this._last_bitmap&&=(hi(this._last_bitmap),null)}_clear_canvas(){let e=this._canvas_context();if(!e)return;let{ctx:t,css_width:n,css_height:r,dpr:i}=e;t.setTransform(i,0,0,i,0,0),t.fillStyle=`#14161b`,t.fillRect(0,0,n,r)}_canvas_context(){if(!this._canvas)return null;let e=this._canvas.getBoundingClientRect(),t=Math.round(e.width),n=Math.round(e.height);if(t<2||n<2)return null;let r=Math.min(Math.max(window.devicePixelRatio||1,1),2),i=Math.max(1,Math.round(t*r)),a=Math.max(1,Math.round(n*r));this._canvas.width!==i&&(this._canvas.width=i),this._canvas.height!==a&&(this._canvas.height=a);let o=this._canvas.getContext(`2d`);return o?{ctx:o,css_width:t,css_height:n,dpr:r}:null}_cache_elements(){this._canvas||=this.querySelector(`.browser-canvas`),this._viewport_el||=this.querySelector(`.browser-viewport`),this._stage_el||=this.querySelector(`.browser-stage`),this._url_input||=this.querySelector(`.browser-url`)}_setup_resize_observer(){this._viewport_el&&(typeof ResizeObserver==`function`?this._resize_observer||(this._resize_observer=new ResizeObserver(()=>this._on_viewport_resize()),this._resize_observer.observe(this._viewport_el)):this._window_resize_bound||=(window.addEventListener(`resize`,this._on_viewport_resize),!0))}_on_viewport_resize(){this._disconnected||(this._last_bitmap&&!this._redraw_scheduled&&(this._redraw_scheduled=!0,requestAnimationFrame(()=>{this._redraw_scheduled=!1,!this._disconnected&&this._last_bitmap&&this._draw_bitmap(this._last_bitmap)})),this._queue_viewport_send(180))}_queue_viewport_send(e){clearTimeout(this._viewport_send_timer),this._viewport_send_timer=setTimeout(()=>{this._viewport_send_timer=null,this._send_viewport()},Math.max(0,e))}_send_viewport(){if(!this._running||this._disconnected||!this._viewport_el)return;let e=this._viewport_el,t=Math.max(0,e.offsetHeight-e.clientHeight),n=Math.round(e.clientWidth),r=Math.round(e.clientHeight+t);if(n<ni||r<ni)return;let i=Math.min(ri,ii/n,ai/r),a=Math.max(320,Math.min(ii,Math.round(n*i))),o=Math.max(240,Math.min(ai,Math.round(r*i))),s=Math.min(Math.max(window.devicePixelRatio||1,1),2),c=Number(s.toFixed(2)),l=`${a}x${o}@${c}`;l!==this._last_viewport_key&&Jr(a,o,c).then(()=>{this._last_viewport_key=l,this._viewport={width:a,height:o,dpr:c},this.requestUpdate()}).catch(e=>{e&&e.status===503&&this._set_error(e)})}_bind_wheel(){!this._wheel_bound&&this._canvas&&(this._canvas.addEventListener(`wheel`,this._on_wheel,{passive:!1}),this._wheel_bound=!0)}_on_wheel(e){if(!this._running)return;if(e.ctrlKey||e.metaKey){e.preventDefault(),this._set_zoom(this._zoom*(e.deltaY<0?ci:1/ci),this._pointer_anchor(e));return}if(this._handoff_to_canvas(e))return;e.preventDefault();let t=this._point_to_frame(e.clientX,e.clientY,!0);t&&(this._queue_input({kind:`wheel`,x:t.x,y:t.y,deltaX:e.deltaX,deltaY:e.deltaY}),this._advance_scroll_cache(e.deltaX,e.deltaY))}_handoff_to_canvas(e){if(this._zoom<=1||!this._scroll_known||!this._viewport_el)return!1;let t=Math.abs(e.deltaX)>Math.abs(e.deltaY),n=t?e.deltaX:e.deltaY;if(!n)return!1;let r=this._scroll;return t?n<0?r.x<=1:r.x>=Math.max(0,r.maxX-1):n<0?r.y<=1:r.y>=Math.max(0,r.maxY-1)}_advance_scroll_cache(e,t){this._scroll_known&&(this._scroll.x=$(this._scroll.x+(e||0),0,this._scroll.maxX),this._scroll.y=$(this._scroll.y+(t||0),0,this._scroll.maxY))}_on_pointerdown(e){if(!this._running||e.button<0)return;this._focus_canvas();let t=this._point_to_frame(e.clientX,e.clientY,!1);if(t){this._pointer_pressed=!0,this._pointer_button=e.button;try{this._canvas.setPointerCapture(e.pointerId)}catch{}this._queue_input({kind:`mouse`,type:`mousePressed`,x:t.x,y:t.y,button:gi(e.button),buttons:e.buttons,clickCount:this._next_click_count(e.button)}),e.preventDefault()}}_on_pointermove(e){if(!this._running)return;let t=this._point_to_frame(e.clientX,e.clientY,!0);t&&this._queue_input({kind:`mouse`,type:`mouseMoved`,x:t.x,y:t.y,button:`none`,buttons:e.buttons,clickCount:0})}_on_pointerup(e){if(!this._pointer_pressed)return;this._pointer_pressed=!1,this._release_pointer(e.pointerId);let t=this._point_to_frame(e.clientX,e.clientY,!0);t&&this._queue_input({kind:`mouse`,type:`mouseReleased`,x:t.x,y:t.y,button:gi(e.button>=0?e.button:this._pointer_button),buttons:e.buttons,clickCount:this._click_count})}_on_pointercancel(e){if(!this._pointer_pressed)return;this._pointer_pressed=!1,this._release_pointer(e.pointerId);let t=this._point_to_frame(e.clientX,e.clientY,!0);t&&this._queue_input({kind:`mouse`,type:`mouseReleased`,x:t.x,y:t.y,button:gi(this._pointer_button),buttons:0,clickCount:this._click_count})}_on_contextmenu(e){e.preventDefault()}_on_canvas_keydown(e){if(e.key===`Escape`&&e.stopPropagation(),e.isComposing||!this._running)return;let t=e.key,n=e.ctrlKey||e.metaKey||e.altKey,r=Qr.has(t),i=t.length===1;if(!r&&!i&&!n)return;e.preventDefault();let a=e.code||``,o=a||t,s={key:t,code:a,keyCode:e.keyCode||0};this._held_keys.has(o)||this._held_keys.set(o,s),this._queue_input({kind:`key`,type:n?`rawKeyDown`:`keyDown`,key:t,code:a,modifiers:this._modifiers(e),text:n?``:i?t:``,windowsVirtualKeyCode:s.keyCode})}_on_canvas_keyup(e){e.key===`Escape`&&e.stopPropagation();let t=e.code||e.key,n=this._held_keys.get(t);n&&(this._held_keys.delete(t),this._running&&(e.preventDefault(),this._queue_input({kind:`key`,type:`keyUp`,key:e.key,code:e.code||n.code,modifiers:this._modifiers(e),text:``,windowsVirtualKeyCode:e.keyCode||n.keyCode||0})))}_on_canvas_blur(){for(let e of this._held_keys.values())this._queue_input({kind:`key`,type:`keyUp`,key:e.key,code:e.code,modifiers:0,text:e.key.length===1?e.key:``});this._held_keys.clear()}_on_paste(e){let t=e.clipboardData?e.clipboardData.getData(`text`):``;t&&(e.preventDefault(),this._running&&this._queue_input({kind:`text`,text:t}))}_modifiers(e){return+!!e.altKey|(e.ctrlKey?2:0)|(e.metaKey?4:0)|(e.shiftKey?8:0)}_next_click_count(e){let t=performance.now();return this._click_count=e===this._last_click_button&&t-this._last_click_time<450?Math.min(this._click_count+1,3):1,this._last_click_time=t,this._last_click_button=e,this._click_count}_point_to_frame(e,t,n){if(!this._canvas)return null;let r=this._canvas.getBoundingClientRect(),i=this._frame_rect,a,o;if(i?(a=(e-r.left-i.x)/Math.max(i.width,1),o=(t-r.top-i.y)/Math.max(i.height,1)):(a=(e-r.left)/Math.max(r.width,1),o=(t-r.top)/Math.max(r.height,1)),!n&&(a<0||a>1||o<0||o>1))return null;let s=this._input_space(),c=Math.max(1,Math.round(s.width)),l=Math.max(1,Math.round(s.height));return{x:Math.min(c-1,Math.round($(a,0,1)*c)),y:Math.min(l-1,Math.round($(o,0,1)*l))}}_input_space(){let e=this._viewport;if(e&&e.width>0&&e.height>0)return e;let t=this._frame_meta||{},n=Number(t.deviceScaleFactor)>0?Number(t.deviceScaleFactor):1,r=Number(t.deviceWidth)||0,i=Number(t.deviceHeight)||0;if(r>0&&i>0)return{width:r/n,height:i/n};let a=this._frame_rect;return a&&a.source_width>0&&a.source_height>0?{width:a.source_width,height:a.source_height}:{width:1,height:1}}_focus_canvas(){if(this._canvas)try{this._canvas.focus({preventScroll:!0})}catch{this._canvas.focus()}}_release_pointer(e){if(this._canvas)try{this._canvas.hasPointerCapture(e)&&this._canvas.releasePointerCapture(e)}catch{}}_queue_input(e){if(this._running&&!this._disconnected){if(e.kind===`mouse`&&e.type===`mouseMoved`){let t=this._input_queue[this._input_queue.length-1];t&&t.kind===`mouse`&&t.type===`mouseMoved`?this._input_queue[this._input_queue.length-1]=e:this._input_queue.push(e)}else this._input_queue.push(e);if(this._input_queue.length>ti){let e=this._input_queue.findIndex(e=>e.kind===`mouse`&&e.type===`mouseMoved`);e!==-1&&this._input_queue.splice(e,1)}this._flush_input()}}async _flush_input(){if(!this._input_flushing){for(this._input_flushing=!0;this._input_queue.length;){let e=this._input_queue.shift();try{await Yr(e)}catch(e){if(e&&e.status===503){this._set_error(e),this._input_queue.length=0;break}}}this._input_flushing=!1}}_set_navigating(e){this._navigating=!!e,clearTimeout(this._navigating_timer),this._navigating_timer=null,this._navigating&&(this._navigating_timer=setTimeout(()=>{this._navigating=!1,this._navigating_timer=null,this.requestUpdate()},15e3)),this.requestUpdate()}_set_error(e){this._error=e&&e.message?e.message:String(e||`Unknown browser error`),this.requestUpdate()}};customElements.define(`browser-panel`,ui);function di(e){let t=String(e?.title||``).trim();if(t)return t;let n=String(e?.url||``).trim();if(!n)return e?.id||`Tab`;try{return new URL(n).hostname||n}catch{return n}}function fi(e){let t=String(e||``).trim();if(!t)return``;if(/^(?:https?|about|file|chrome|data):/i.test(t))return t;let n=t.split(/[/?#]/,1)[0],r=/^(?:localhost|\d{1,3}(?:\.\d{1,3}){3}|\[[0-9a-f:]+\])(?::\d+)?$/i.test(n)||/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?::\d+)?$/i.test(n);return!/\s/.test(t)&&r?t:`https://www.google.com/search?q=${encodeURIComponent(t)}`}function pi(e){let t=e.indexOf(`,`),n=e.startsWith(`data:`)&&t!==-1?e.slice(t+1):e,r=atob(n.replace(/\s+/g,``)),i=new Uint8Array(r.length);for(let e=0;e<r.length;e+=1)i[e]=r.charCodeAt(e);return new Blob([i],{type:`image/jpeg`})}function mi(e){return new Promise((t,n)=>{let r=URL.createObjectURL(e),i=new Image;i.decoding=`async`,i.onload=()=>{URL.revokeObjectURL(r),t(i)},i.onerror=()=>{URL.revokeObjectURL(r),n(Error(`Frame decode failed`))},i.src=r})}function hi(e){e&&typeof e.close==`function`&&e.close()}function $(e,t,n){return Math.min(Math.max(e,t),n)}function gi(e){switch(e){case 1:return`middle`;case 2:return`right`;case 3:return`back`;case 4:return`forward`;default:return`left`}}var _i=class extends k{createRenderRoot(){return this}render(){return C`
      <aside class="workbench-panel" aria-label="Browser and background commands">
        <browser-panel></browser-panel>
        <background-panel></background-panel>
      </aside>
    `}};customElements.define(`workbench-panel`,_i);var vi=120,yi=class extends k{static properties={open:{type:Boolean}};constructor(){super(),this.open=!1,this._path=``,this._name=``,this._error=``,this._busy=!1,this._suggestions=[],this._suggestions_open=!1,this._active_index=-1,this._suggest_timer=null,this._request_seq=0,this._focus_pending=!1,this._document_listener=null}createRenderRoot(){return this}disconnectedCallback(){this._stop_listening(),clearTimeout(this._suggest_timer),super.disconnectedCallback()}willUpdate(e){e.has(`open`)&&(this.open?(this._error=``,this._focus_pending=!0,this._start_listening()):(this._stop_listening(),this._close_suggestions()))}updated(){this.open&&this._focus_pending&&(this._focus_pending=!1,this.querySelector(`.workspace-path-input`)?.focus())}render(){return this.open?C`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="workspace-dialog-title"
          @click=${this._stop}
        >
          <h2 id="workspace-dialog-title">Add workspace</h2>
          <label class="modal-field">
            <span>Folder path</span>
            <input
              class="workspace-path-input"
              type="text"
              .value=${this._path}
              placeholder="/path/to/project"
              autocomplete="off"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded=${this._suggestions_open}
              aria-controls="workspace-path-suggestions"
              @input=${this._on_path}
              @focus=${this._on_path_focus}
              @keydown=${this._on_keydown}
            />
          </label>
          ${this._render_suggestions()}
          <label class="modal-field">
            <span>Display name</span>
            <input
              type="text"
              .value=${this._name}
              placeholder="Optional label"
              @input=${this._on_name}
              @focus=${this._on_name_focus}
              @keydown=${this._on_keydown}
            />
          </label>
          <p class="modal-hint">Saved to .cecli/conf.yml and opened as a new session.</p>
          ${this._error?C`<p class="modal-error">${this._error}</p>`:T}
          <div class="modal-actions">
            <button type="button" class="modal-btn" @click=${this._close}>Cancel</button>
            <button
              type="button"
              class="modal-btn modal-btn--primary"
              ?disabled=${this._busy}
              @click=${this._submit}
            >
              ${this._busy?`Adding…`:`Add workspace`}
            </button>
          </div>
        </div>
      </div>
    `:T}_render_suggestions(){return this._suggestions_open?C`
      <ul class="path-suggestions" id="workspace-path-suggestions" role="listbox">
        ${this._suggestions.map((e,t)=>C`
            <li role="option" aria-selected=${t===this._active_index}>
              <button
                type="button"
                class="path-suggestion"
                data-active=${t===this._active_index}
                @mousedown=${this._keep_focus}
                @click=${()=>this._choose(e)}
              >
                <span class="path-suggestion-name">${e.name}</span>
                <span class="path-suggestion-path">${e.path}</span>
              </button>
            </li>
          `)}
      </ul>
    `:T}_on_backdrop(){this._busy||this._close()}_on_path(e){this._path=e.target.value,this._queue_suggestions()}_on_path_focus(){this._suggestions_open||this._queue_suggestions(0)}_on_name(e){this._name=e.target.value}_on_name_focus(){this._close_suggestions()}_on_keydown(e){let t=e.target.classList.contains(`workspace-path-input`);if(e.key===`Escape`){if(this._suggestions_open){this._close_suggestions(),e.stopPropagation();return}this._close()}else{if(t&&this._suggestions_open&&this._suggestions.length){if(e.key===`ArrowDown`){e.preventDefault(),this._move_active(1);return}if(e.key===`ArrowUp`){e.preventDefault(),this._move_active(-1);return}if(e.key===`Tab`||e.key===`Enter`){e.preventDefault();let t=this._active_index>=0?this._active_index:0;this._choose(this._suggestions[t]);return}}e.key===`Enter`&&!e.isComposing&&this._submit()}}_stop(e){e.stopPropagation()}_keep_focus(e){e.preventDefault()}_queue_suggestions(e=vi){clearTimeout(this._suggest_timer),this._suggest_timer=setTimeout(()=>this._fetch_suggestions(),e)}async _fetch_suggestions(){let e=++this._request_seq;try{let t=await et(this._path);if(e!==this._request_seq)return;this._suggestions=Array.isArray(t.entries)?t.entries:[],this._suggestions_open=this._suggestions.length>0,this._active_index=-1}catch{if(e!==this._request_seq)return;this._suggestions=[],this._suggestions_open=!1}this.requestUpdate()}_move_active(e){let t=this._suggestions.length;t&&(this._active_index=this._active_index<0?e>0?0:t-1:(this._active_index+e+t)%t,this.requestUpdate())}_choose(e){this._path=e.path,this._name.trim()||(this._name=e.name),this._close_suggestions()}_close_suggestions(){this._suggestions=[],this._suggestions_open=!1,this._active_index=-1,this.requestUpdate()}_start_listening(){this._document_listener||(this._document_listener=e=>{this.contains(e.target)||this._close_suggestions()},document.addEventListener(`pointerdown`,this._document_listener))}_stop_listening(){this._document_listener&&=(document.removeEventListener(`pointerdown`,this._document_listener),null)}async _submit(){if(this._busy)return;let e=this._path.trim();if(!e)this._error=`A folder path is required`;else{this._busy=!0,this._error=``,this._close_suggestions();try{await X.add_workspace(e,this._name.trim()||null),this._close()}catch(e){this._error=e.message}finally{this._busy=!1,this.requestUpdate()}}}_close(){clearTimeout(this._suggest_timer),this._path=``,this._name=``,this._error=``,this._busy=!1,this._suggestions=[],this._suggestions_open=!1,this._active_index=-1,this._stop_listening(),this.open=!1,this.dispatchEvent(new CustomEvent(`close`,{bubbles:!0,composed:!0}))}};customElements.define(`workspace-dialog`,yi);var bi=class extends k{constructor(){super(),this._store=new K(this,J),this._workspace_dialog_open=!1,this._chat_collapsed=!1,this._sidebar_collapsed=!1,this._workbench_collapsed=!1}createRenderRoot(){return this}render(){return C`
      <app-backdrop></app-backdrop>
      <div class="app-shell">
        <app-header
          .chatCollapsed=${this._chat_collapsed}
          .sidebarCollapsed=${this._sidebar_collapsed}
          .workbenchCollapsed=${this._workbench_collapsed}
          @toggle-pane=${this._on_toggle_pane}
        ></app-header>
        <div
          class="workspace-shell"
          data-chat-collapsed=${String(this._chat_collapsed)}
          data-sidebar-collapsed=${String(this._sidebar_collapsed)}
          data-workbench-collapsed=${String(this._workbench_collapsed)}
        >
          <session-sidebar @add-workspace=${this._on_add_workspace}></session-sidebar>
          <main class="chat-panel">
            <transcript-view></transcript-view>
            <permission-region></permission-region>
            <div class="composer-dock">
              <agent-strip></agent-strip>
              <composer-bar></composer-bar>
              <control-strip @open-onboarding=${this._open_onboarding}></control-strip>
            </div>
          </main>
          <workbench-panel></workbench-panel>
        </div>
      </div>
      <toast-stack></toast-stack>
      <workspace-dialog
        .open=${this._workspace_dialog_open}
        @close=${this._on_workspace_dialog_close}
      ></workspace-dialog>
      <onboarding-dialog .open=${!!this._store.state.onboarding_open}></onboarding-dialog>
    `}_on_toggle_pane(e){let t=e.detail&&e.detail.pane;t===`sidebar`?this._sidebar_collapsed=!this._sidebar_collapsed:t===`chat`?(this._chat_collapsed=!this._chat_collapsed,this._chat_collapsed&&(this._workbench_collapsed=!1)):t===`workbench`&&(this._workbench_collapsed=!this._workbench_collapsed,this._workbench_collapsed&&(this._chat_collapsed=!1)),this.requestUpdate()}_on_add_workspace(){this._workspace_dialog_open=!0,this.requestUpdate()}_on_workspace_dialog_close(){this._workspace_dialog_open=!1,this.requestUpdate()}_open_onboarding(){X.open_onboarding()}};customElements.define(`cecli-app`,bi),X.start();