"""Power/memory consent and a visible stop surface precede every LP inference."""
import json
import secrets
import threading
import time
import uuid


TERMINAL={"completed","incomplete","failed","cancelled","timed_out"}


class InferenceControls:
    def __init__(self, app):
        self.app=app;self.lock=threading.RLock();self.stop_event=threading.Event()
        self.current=app.store.get("inference_control")
        self.authorized_nonce=None;self._test_bypass=False;self.last_heartbeat=0
        self.desktop_surface=None
        if self.current and self.current.get("phase") in {"starting","running"} and not self.current.get("task_id"):
            self.current["phase"]="recovery_required"

    def options(self):
        saved=self.app.store.get("inference_options",{})
        return {"allow_local_on_battery":saved.get("allow_local_on_battery",self.app.config.allow_local_on_battery),
                "allow_automatic_cloud":saved.get("allow_automatic_cloud",self.app.config.allow_automatic_cloud)}

    def public(self):
        if not self.current:return None
        return {k:v for k,v in self.current.items() if k not in {"nonce","submission_id"}}

    def save(self):self.app.store.set("inference_control",self.current)

    def ui_live(self):
        if self.desktop_surface and time.monotonic()-self.desktop_surface['seen']<20:
            try:
                import psutil
                process=psutil.Process(self.desktop_surface['pid'])
                if abs(process.create_time()-self.desktop_surface['created'])<.02 and process.status()!=psutil.STATUS_ZOMBIE:return True
            except psutil.Error:pass
        try:
            from companion.ui.build import _owned_process
            record=json.loads(self.app.private.file("ui.json").read_text())
            _owned_process(record,self.app.private,self.app.token)
            return True
        except Exception as exc:
            self.ui_identity_error=type(exc).__name__+": "+str(exc)[:150]
            return False

    def desktop_presented(self,ticket,pid,preferences):
        if not self.app.config.desktop_control_enabled or not self.current or self.current['id']!=ticket:return {'status':'stale_control'}
        import os,plistlib,psutil
        from pathlib import Path
        try:
            if (not isinstance(preferences,dict) or set(preferences)!={'version','source','objective'} or preferences['version']!='1.0' or preferences['source'] not in {'local_only','local_first','balanced','cloud_first','cloud_only'} or preferences['objective'] not in {'speed','quality','efficiency','balanced'}):raise ValueError('Invalid preferences')
            if (preferences['source']=='local_only' and self.current['kind']=='cloud') or (preferences['source']=='cloud_only' and self.current['kind']=='local'):return {'status':'denied','text':'本会话来源限制禁止该委派'}
            process=psutil.Process(pid);exe=Path(process.exe())
            if process.uids().real!=os.getuid() or exe.name!='localpilot-desktop' or exe.parent.name!='MacOS':raise ValueError('Wrong executable')
            info=plistlib.loads((exe.parent.parent/'Info.plist').read_bytes())
            if not str(info.get('CFBundleIdentifier','')).startswith('io.localpilot.desktop'):raise ValueError('Wrong bundle')
            self.desktop_surface={'pid':pid,'created':process.create_time(),'seen':time.monotonic()}
            self.current['routing_preferences']=preferences
            self.current['conversation_id']='desktop-'+self.current['id']
            return self.ack(ticket)
        except (OSError,ValueError,psutil.Error):return {'status':'ui_required'}

    def requirements(self, kind, minimum=None, *, mode="reasoning", help_authorized=False, force_cloud_confirmation=False):
        self.app.resources.poll(force=True)
        state=self.app.resources.latest;options=self.options();required=[]
        if kind=="local":
            if state.get("on_ac_power") is not True and not options["allow_local_on_battery"]:
                required.append("battery_or_unknown_power")
            if state.get("memory_available_bytes",0)<(minimum or self.app.config.local_model_min_available_bytes):
                required.append("memory_wall")
        elif not options["allow_automatic_cloud"] or force_cloud_confirmation:required.append("cloud_question_egress")
        if mode=="execution" and not help_authorized:required.append("agent_help")
        return required,state

    def prepare(self, kind="local", mode="reasoning", *, force_cloud_confirmation=False, fallback=None):
        with self.lock:
            if self.current and self.current.get("phase") in {"starting","running","stopping","draining","cleanup_required"}:
                return {"status":"inference_busy","text":"上一项推理仍在运行或停止中，请先处理控制窗。","control":self.public()}
            if kind=="cloud" and mode!="reasoning":
                return {"status":"denied","text":"云端咨询与 Agent 执行分开；不能把执行任务直接重放给云端。"}
            provider=self.app.cloud_localpilot if kind=="cloud" else self.app.localpilot
            health=provider.health(cloud_approved=kind=="cloud")
            if health.get("status")!="available":
                return health | {"text":"LocalPilot 暂不可用；没有启动大模型。"}
            if provider.resource_control_version!=1:
                return {"status":"unavailable","text":"LocalPilot 尚未接入推理停止控制，本次未启动大模型。"}
            try:
                registry=provider._request("/localpilot/v1/model-registry",cloud_approved=kind=="cloud")
                route=self.app.config.localpilot_cloud_analysis_route if kind=="cloud" else self.app.config.localpilot_analysis_route if mode=="reasoning" else self.app.config.localpilot_route
                entry=next((m for m in registry.get("models",[]) if m.get("id")==route),{})
            except Exception:return {"status":"unavailable","text":"推理路由暂时无法核验。"}
            if kind=="cloud" and entry.get("adapter") not in {"deepseek","deepseek-native"}:
                return {"status":"unavailable","text":"没有可核验的 DeepSeek 极简咨询路由；未发送问题。"}
            lifecycle=entry.get("local_model_lifecycle",{})
            if kind=='local' and entry.get('adapter')=='omlx' and entry.get('deployment_status')!='ready':
                return {'status':'unavailable','text':'本地模型尚未加载。请在模型库单独授权加载后再确认帮助；本次没有提交任务。'}
            shared=(lifecycle.get('shared_external_service') is True and lifecycle.get('request_cancel_supported') is True and entry.get('deployment_status')=='ready')
            if kind=="local" and not shared and (lifecycle.get("release_after_task") is not True or lifecycle.get("control_surface_required") is not True):
                return {"status":"unavailable","text":"本地路由还没有可控启停与自动释放能力，本次未启动大模型。"}
            minimum=max(4*1024**3 if shared else self.app.config.local_model_min_available_bytes,lifecycle.get("minimum_available_bytes",0))
            required,state=self.requirements(kind,minimum,mode=mode,force_cloud_confirmation=force_cloud_confirmation)
            pending=self.app.store.get("pending_escalation")
            self.current={"id":uuid.uuid4().hex,"phase":"prepared","kind":kind,"mode":mode,
                "question":str((pending or {}).get("user_request",""))[:500],
                "digest":self.app.review_digest(pending),"scope":self.app.privacy.consent_id(),
                "required_confirmations":required,"resources":state,"force_cloud_confirmation":force_cloud_confirmation,"fallback":fallback,"created_at":time.time(),
                "expires_at":time.time()+300,"memory_wall_bytes":minimum,"panel_presented":False,"task_id":None,
                "model":self.app.config.localpilot_expected_local_model if kind=="local" else "DeepSeek · "+str(entry.get("model","已配置模型"))[:120]+"（仅原问题）"}
            self.stop_event=threading.Event();self.save()
            return {"status":"inference_prepared","text":"已准备推理控制窗；显示停止按钮后才会开始调用。","control":self.public()}

    def help_authorized(self, current):
        grant=current.get("help_grant") or {}
        return grant.get("digest")==current.get("digest") and grant.get("scope")==current.get("scope") and 0<=time.time()-grant.get("at",0)<300

    def grant_notice_help(self, notice_id):
        current=self.current
        if current and current.get("phase")=="prepared" and current.get("mode")=="execution":
            current["help_grant"]={"digest":current["digest"],"scope":current["scope"],"at":time.time(),"source":"user_notice_help","notice_id":notice_id}
            current["required_confirmations"]=[x for x in current["required_confirmations"] if x!="agent_help"]
            self.save()

    def ack(self, ticket):
        if not self.current or self.current["id"]!=ticket or self.current["phase"]!="prepared":return {"status":"stale_control"}
        if not self.ui_live():return {"status":"ui_required","text":"需要当前 Companion 控制窗保持可用。"}
        self.current["panel_presented"]=True
        required,state=self.requirements(self.current["kind"],self.current.get("memory_wall_bytes"),mode=self.current["mode"],help_authorized=self.help_authorized(self.current),force_cloud_confirmation=self.current.get("force_cloud_confirmation",False))
        self.current.update(required_confirmations=required,resources=state);self.save()
        return {"status":"confirmation_required" if required else "ready_to_start","control":self.public()}

    def start(self, ticket, confirmed=False):
        with self.lock:
            current=self.current
            if not current or current["id"]!=ticket or current["phase"]!="prepared" or self.stop_event.is_set():
                return {"status":"stopped","text":"这次推理已取消或不再有效。"}
            if not current["panel_presented"] or not self.ui_live():return {"status":"ui_required"}
            if current["expires_at"]<time.time() or current["digest"]!=self.app.review_digest(self.app.store.get("pending_escalation")) or current["scope"]!=self.app.privacy.consent_id():
                return {"status":"review_changed","text":"上下文或权限已变化，请重新准备。"}
            if current["kind"]=="local":self.app.model.unload()
            required,state=self.requirements(current["kind"],current.get("memory_wall_bytes"),mode=current["mode"],help_authorized=self.help_authorized(current),force_cloud_confirmation=current.get("force_cloud_confirmation",False))
            newly_required=set(required)-set(current.get("required_confirmations",[]))
            if required and (confirmed is not True or newly_required):
                current.update(required_confirmations=required,resources=state);self.save()
                return {"status":"confirmation_required","control":self.public()}
            scopes=[]
            if "memory_wall" in required:scopes.append("memory")
            if current["kind"]=="local" and (self.options()["allow_local_on_battery"] or "battery_or_unknown_power" in required):scopes.append("battery")
            current["resource_scopes"]=scopes
            current["phase"]="starting";current["confirmed_once"]=confirmed is True
            if current["mode"]=="execution" and confirmed is True:
                current["help_grant"]={"digest":current["digest"],"scope":current["scope"],"at":time.time(),"source":"explicit_control_confirmation"}
            self.authorized_nonce=secrets.token_urlsafe(32);self.save()
            nonce=self.authorized_nonce
        try:
            result=self.app.command({"command":"submit_escalation","approved":True,
                "expected_digest":current["digest"],"automatic_local":current["kind"]=="local",
                "provider_kind":current["kind"],"cloud_approved":current["kind"]=="cloud",
                "memory_ticket":current["id"] if scopes else None,"resource_scopes":scopes,"control_ticket":current["id"],
                "_host_control_nonce":nonce,"defer_monitor":True,"user_help_approved":current["mode"]=="execution" and self.help_authorized(current),
                **({'routing_preferences':current['routing_preferences']} if current.get('routing_preferences') else {}),
                **({'conversation_id':current['conversation_id']} if current.get('conversation_id') else {})})
        finally:self.authorized_nonce=None
        with self.lock:
            if result.get("task_id"):
                current["task_id"]=result["task_id"];current["phase"]=("draining" if current["kind"]=="cloud" else "stopping") if self.stop_event.is_set() else "running"
                if result.get("quiescent") and result.get("status") in TERMINAL:
                    resource=result.get("model_resource") or {}
                    current["phase"]="cleanup_required" if resource.get("managed") is True and resource.get("model_process_alive") is not False else "finished"
            else:
                current["phase"]="recovery_required" if result.get("status")=="submission_unknown" else "blocked"
                current["last_status"]=self.app.task_summary(result)
            self.save()
        if result.get("task_id"):
            provider=self.provider()
            if current["kind"]=="cloud" and not self.stop_event.is_set() and result.get("status")=="requires_approval":
                current["cloud_action_attempted"]=(result.get("required_action") or {}).get("id")
                result=provider.approve_cloud_egress(result["task_id"],(result.get("required_action") or {}).get("id",""))
            self.app.monitor_task(current["task_id"],0,current["kind"]=="cloud",provider=provider)
        message=result.get("agent_response")
        if not message:
            message=("推理已提交；可随时在控制窗停止。" if result.get("task_id") else
                     "提交状态待核对；请恢复原任务，不要换键重放。" if result.get("status")=="submission_unknown" else
                     "本次未能提交：" + str((result.get("error") or {}).get("code") or result.get("reason") or result.get("status")))
        return result | {"control":self.public(),"text":message}

    def heartbeat(self, ticket):
        current=self.current
        if not current or current["id"]!=ticket:return {"status":"stale_control"}
        if self.desktop_surface:self.desktop_surface['seen']=time.monotonic()
        if not self.ui_live():return {"status":"ui_required"}
        now=time.time()
        if current.get("task_id") and current.get("phase") in {"starting","running","stopping","draining","cleanup_required"} and now-self.last_heartbeat>=8:
            self.last_heartbeat=now;provider=self.provider();task_id=current["task_id"]
            threading.Thread(target=lambda:provider.control_heartbeat(task_id,ticket),daemon=True,name="CompanionControlHeartbeat").start()
        return {"status":"ok"}

    def provider(self):return self.app.cloud_localpilot if self.current and self.current["kind"]=="cloud" else self.app.localpilot

    def bind_submission(self, submission_id):
        with self.lock:
            if self.current and self.current.get("phase")=="starting":self.current["submission_id"]=submission_id

    def stop_async(self, ticket, future, origin="user_control"):
        with self.lock:
            if not self.current or self.current["id"]!=ticket:
                future.set_result({"status":"stale_control"});return
            if self.current.get("phase") in {"finished","stopped","blocked"}:
                future.set_result({"status":"already_finished","control":self.public()});return
            self.current["stop_origin"]=origin
            self.stop_event.set();current=dict(self.current)
            self.current["phase"]="draining" if current["kind"]=="cloud" else "stopping"
            provider=self.provider()
            if current.get("submission_id"):provider.cancelled_submissions.add(current["submission_id"])
        future.set_result({"status":"stopping","text":"正在停止；云端已发出的本轮回复会尽量接收完整。"})
        def work():
            if current.get("phase")=="prepared":result={"status":"stopped_before_submission","tasks":[]}
            else:result=provider.emergency_stop(current.get("task_id"),drain=current["kind"]=="cloud",submission_id=current.get("submission_id"))
            self.app.queue.put(("inference_control_stop",ticket,result))
        threading.Thread(target=work,name="CompanionInferenceStop",daemon=True).start()

    def stopped(self, ticket, result):
        if not self.current or self.current["id"]!=ticket:return
        self.current["stop_result"]={k:v for k,v in result.items() if k!="tasks"}
        self.current["phase"]="stop_unconfirmed" if result.get("status")=="stop_unconfirmed" else "draining" if self.current["kind"]=="cloud" and self.current.get("task_id") else "stopped"
        bindings=result.get("request_bindings",{})
        key=self.current.get("submission_id")
        if key and not self.current.get("task_id") and result.get("status")!="stop_unconfirmed":
            import hashlib
            namespace=hashlib.sha256((self.app.config.localpilot_client_subject+"\0"+key).encode()).hexdigest()
            expected=hashlib.sha256(namespace.encode()).hexdigest()
            match=next((task for task in result.get("tasks",[]) if bindings.get(task["id"])==expected),None)
            if match:
                from companion.escalation.localpilot import task_view
                intent=self.app.store.get("pending_localpilot_submission")
                if intent and intent["submission_id"]==key:
                    intent["result"]=self.app.task_summary(task_view(match))
                    self.app.store.set("pending_localpilot_submission",intent);self.app.recover_submission_journal()
                self.current["task_id"]=match["id"]
            else:
                # The authenticated persisted stop fence rejects any delayed
                # POST from the stopped generation; no new key is replayed.
                self.app.store.set("pending_localpilot_submission",None)
                self.app.store.set("pending_escalation",None)
        for task in result.get("tasks",[]):
            from companion.escalation.localpilot import task_view
            self.app.receive_task_update(task["id"],task_view(task))
        self.save()

    def task_update(self, task_id, result):
        if self.current and self.current.get("task_id")==task_id:
            self.current["last_status"]=self.app.task_summary(result)
            if result.get("quiescent") and result.get("status") in TERMINAL:
                resource=result.get("model_resource") or {}
                self.current["phase"]="cleanup_required" if resource.get("managed") is True and resource.get("model_process_alive") is not False else "finished"
            self.save()
