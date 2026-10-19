/* Snap2Todo 待办管理界面（T10 源实现注释保留）。
 * 原生 JS，无框架、无构建、无外部资源。
 * 分区：apiClient（HTTP）/ formMapping（纯函数，无 DOM）/ 视图（DOM）。
 */
/* 待办模块交互逻辑：完整移植自 Snap2Todo web/app.js（只读源文件）。
 * 相对源实现的必要改造（工作台集成）：
 *  1. IIFE -> 可挂载/卸载的 createTasksApp(scope, deps)，所有状态按实例隔离；
 *  2. 内部路由（#/import #/review #/tasks #/tasks/{id}）只改内存状态，绝不写
 *     location.hash，避免与工作台外壳 createRouter 的路由互相触发；模块内
 *     href="#/..." 链接统一拦截后走内部 navigate()；
 *  3. 所有 /api/v1/* 请求经 deps.fetchRaw（core/api.js 的 api.raw）自动带
 *     X-Workbench-Token；/sources/{id}/content 原图回看同样走它；
 *  4. 源图标 use href="#t-i-*" 改为 "#t-i-*"（与外壳 core/icons.js sprite 隔离）；
 *  5. 图片预览与原图回看转 data: URL（工作台 CSP: img-src 'self' data:，blob: 被拦截）；
 *  6. window/document 监听、5 秒提醒轮询、弹层与预览 URL 在 destroy() 中统一清理。
 */
/* 手动新建待办：对话框输入 → POST /api/v1/tasks 请求体（纯函数，无 DOM）。
   放在模块作用域，node 测试可直接导入本文件验证载荷形状（契约 §4.2）：
   - 只填日期时 precision=date，resolvedValue 必须严格是 YYYY-MM-DD；
   - 填了时间才是 datetime（工作台固定 Asia/Shanghai，+08:00，无夏令时）；
   - 提醒三选一：不提醒 / 提前 N 分钟（相对截止时间）/ 指定提醒时间（绝对时刻）。 */
export function buildManualTaskPayload(input) {
  var values = input || {};
  var date = values.date || "";
  var time = values.time || "";
  var requirements = (values.requirements || "")
    .split("\n")
    .map(function (line) { return line.trim(); })
    .filter(function (line) { return line.length > 0; });
  var reminderMode = values.reminderMode || "none";
  var payload = {
    title: (values.title || "").trim(),
    requirements: requirements,
  };
  if (date) {
    payload.dueTime = {
      rawExpression: time ? date + " " + time : date,
      precision: time ? "datetime" : "date",
      // 仅日期绝不能补默认时刻：date 精度下带 T09:00 会被后端判为非法载荷。
      resolvedValue: time ? localIsoWithOffset(date, time) : date,
      status: "resolved",
    };
  }
  if (reminderMode === "relative") {
    payload.reminder = {
      mode: "relative",
      requestedAt: null,
      relativeTo: "due",
      offsetMinutes: Number(values.reminderOffset),
    };
  } else if (reminderMode === "manual") {
    payload.reminder = {
      mode: "manual",
      requestedAt: localDateTimeToIso(values.reminderAt),
      relativeTo: null,
      offsetMinutes: null,
    };
  } else {
    payload.reminder = {
      mode: "none",
      requestedAt: null,
      relativeTo: null,
      offsetMinutes: null,
    };
  }
  return payload;
}

function localDateTimeToIso(value) {
  // 输入为本地 datetime-local（YYYY-MM-DDTHH:mm）；工作台固定 Asia/Shanghai（+08:00，无夏令时）
  if (!value) return null;
  var parts = String(value).split("T");
  if (parts.length !== 2) return null;
  return localIsoWithOffset(parts[0], parts[1]);
}

function localIsoWithOffset(dateValue, timeValue) {
  // 输入是本地日期/时间；工作台固定 Asia/Shanghai（+08:00，无夏令时）
  var time = timeValue.length === 5 ? timeValue + ":00" : timeValue;
  return dateValue + "T" + time + "+08:00";
}

export function createTasksApp(scope, deps) {
  "use strict";
  var fetchRaw = deps.fetchRaw;
  var disposers = [];
  function listen(target, type, handler, options) {
    target.addEventListener(type, handler, options);
    disposers.push(function () { target.removeEventListener(type, handler, options); });
  }

  // ============================================================== apiClient
  // 统一 fetch 封装：解析契约错误包 {error:{code,message,details}}。
  // 成功返回解析后的 JSON；失败抛 ApiError {code,message,fieldErrors,status}。
  function ApiError(status, code, message, fieldErrors) {
    this.status = status;
    this.code = code;
    this.message = message;
    this.fieldErrors = fieldErrors || [];
  }

  async function request(method, path, body, asText, isForm) {
    var options = { method: method, headers: {} };
    if (body !== undefined) {
      if (isForm) {
        // multipart：边界由浏览器生成，绝不手写 Content-Type（T13）
        options.body = body;
      } else {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
      }
    }
    var response;
    try {
      response = await fetchRaw(path, options);
    } catch (e) {
      // 网络错误：无 HTTP 状态
      throw new ApiError(0, "network_error", "无法连接本地服务，请检查服务是否已启动。");
    }
    var text = await response.text();
    var contentType = response.headers.get("Content-Type") || "";
    var isJson = contentType.indexOf("application/json") !== -1;

    if (response.status === 204) {
      return null;
    }

    if (!response.ok) {
      // 错误响应一律按契约错误包 {error:{code,message,details}} 解析
      var errorPayload = null;
      try {
        errorPayload = text ? JSON.parse(text) : null;
      } catch (e) {
        errorPayload = null;
      }
      var error = errorPayload && errorPayload.error ? errorPayload.error : {};
      var details = error.details || {};
      throw new ApiError(
        response.status,
        error.code || "unknown_error",
        error.message || (isJson ? "请求失败。" : text || "请求失败。"),
        details.fieldErrors || []
      );
    }

    // 成功响应：非 JSON（如 text/plain 原文）按文本返回，不强行解析
    if (asText || !isJson) {
      return text;
    }
    var payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch (e) {
      throw new ApiError(response.status, "invalid_response", "服务返回了无法解析的内容。");
    }
    return payload;
  }

  var apiClient = {
    listTasks: function (status) {
      var query = status && status !== "open" ? "?status=" + encodeURIComponent(status) : "";
      return request("GET", "/api/v1/tasks" + query);
    },
    // 期6-B：长期任务（目标）CRUD。GET /goals/{id} 在期3后端会附带 progress。
    listGoals: function (status) {
      return request("GET", "/api/v1/goals?status=" + encodeURIComponent(status || "active"));
    },
    getGoal: function (id) {
      return request("GET", "/api/v1/goals/" + encodeURIComponent(id));
    },
    createGoal: function (body) {
      return request("POST", "/api/v1/goals", body);
    },
    archiveGoal: function (id) {
      return request("DELETE", "/api/v1/goals/" + encodeURIComponent(id));
    },
    listGoalTasks: function (goalId) {
      return request("GET", "/api/v1/tasks?status=all&goalId=" + encodeURIComponent(goalId));
    },
    // 期6-C：AI 规划（只返回草稿，不落库）、草稿确认落库、习惯实例生成
    planGoal: function (id) {
      // 本期不单独提供「不可用日」选择，传空对象即可（后端 body 可省略）。
      return request("POST", "/api/v1/goals/" + encodeURIComponent(id) + "/plan", {});
    },
    saveGoalTasks: function (id, drafts, planRevision) {
      return request("POST", "/api/v1/goals/" + encodeURIComponent(id) + "/tasks", {
        drafts: drafts,
        planRevision: planRevision,
      });
    },
    generateGoalOccurrences: function (id) {
      return request("POST", "/api/v1/goals/" + encodeURIComponent(id) + "/occurrences", {});
    },
    getTask: function (id) {
      return request("GET", "/api/v1/tasks/" + encodeURIComponent(id));
    },
    patchTask: function (id, body) {
      return request("PATCH", "/api/v1/tasks/" + encodeURIComponent(id), body);
    },
    createTask: function (body) {
      return request("POST", "/api/v1/tasks", body);
    },
    deleteTask: function (id) {
      return request("DELETE", "/api/v1/tasks/" + encodeURIComponent(id));
    },
    getSource: function (id) {
      return request("GET", "/api/v1/sources/" + encodeURIComponent(id));
    },
    getSourceContent: function (id) {
      // /content 对 text 源返回 text/plain 原文（契约 §4），走文本分支
      return request("GET", "/api/v1/sources/" + encodeURIComponent(id) + "/content", undefined, true);
    },
    extract: function (payload) {
      return request("POST", "/api/v1/extractions", payload);
    },
    // T13：截图导入走 multipart（file + messageDate）
    extractImage: function (formData) {
      return request("POST", "/api/v1/extractions", formData, false, true);
    },
    confirmDraftSet: function (draftSetId, payload) {
      return request(
        "POST",
        "/api/v1/draft-sets/" + encodeURIComponent(draftSetId) + "/confirm",
        payload
      );
    },
    // T13：图片确认必须重传原图（file）+ confirmation JSON 部件
    confirmImage: function (draftSetId, file, payload) {
      var form = new FormData();
      form.append("file", file, file && file.name ? file.name : "shot.png");
      form.append("confirmation", JSON.stringify(payload));
      return request(
        "POST",
        "/api/v1/draft-sets/" + encodeURIComponent(draftSetId) + "/confirm",
        form,
        false,
        true
      );
    },
    // T13：image 源原文回看 → /content 原始字节 → blob URL
    getSourceImage: async function (id) {
      var response;
      try {
        response = await fetchRaw("/api/v1/sources/" + encodeURIComponent(id) + "/content");
      } catch (e) {
        throw new ApiError(0, "network_error", MODEL_ERROR_TEXT.network_error);
      }
      if (!response.ok) {
        var text = "";
        try { text = await response.text(); } catch (e) { text = ""; }
        var payload = null;
        try { payload = text ? JSON.parse(text) : null; } catch (e) { payload = null; }
        var error = payload && payload.error ? payload.error : {};
        throw new ApiError(
          response.status,
          error.code || "unknown_error",
          error.message || "原图读取失败。"
        );
      }
      var blob = await response.blob();
      return await readAsDataUrl(blob);
    },
    // T15：提醒会话与确认
    openReminderSession: function () {
      return request("POST", "/api/v1/reminder-sessions");
    },
    dueReminders: function (sessionId) {
      return request(
        "GET",
        "/api/v1/reminder-sessions/" + encodeURIComponent(sessionId) + "/due"
      );
    },
    acknowledgeReminder: function (args) {
      return request(
        "POST",
        "/api/v1/reminders/" + encodeURIComponent(args.taskId) + "/acknowledgment",
        { sessionId: args.sessionId, reminderVersion: args.reminderVersion }
      );
    },
  };

  // ============================================================== formMapping
  // 纯函数区：表单值 ↔ 契约 JSON。不触碰 DOM，可独立测试。
  // TimeInfo 表单形状：{enabled, rawExpression, precision, resolvedValue, needsConfirmation}
  // Reminder 表单形状：{mode, requestedAt, relativeTo, offsetMinutes}（字符串）

  function _blankToNull(value) {
    return value === "" || value === undefined ? null : value;
  }

  var formMapping = {
    // TimeInfo：表单 → TimeInfoInput（四键，timeZone 服务端固定）
    timeInfoFromForm: function (form) {
      if (!form || !form.enabled) return null;
      return {
        rawExpression: _blankToNull((form.rawExpression || "").trim() === "" ? "" : form.rawExpression),
        precision: form.precision,
        resolvedValue: form.needsConfirmation ? null : _blankToNull(form.resolvedValue),
        status: form.needsConfirmation ? "needs_confirmation" : "resolved",
      };
    },
    // TimeInfoInput → 表单
    timeInfoToForm: function (json) {
      if (!json) {
        return {
          enabled: false,
          rawExpression: "",
          precision: "date",
          resolvedValue: "",
          needsConfirmation: false,
        };
      }
      return {
        enabled: true,
        rawExpression: json.rawExpression || "",
        precision: json.precision,
        resolvedValue: json.resolvedValue || "",
        needsConfirmation: json.status === "needs_confirmation",
      };
    },

    // Reminder：表单 → ReminderInput（四键，模式矩阵）
    reminderFromForm: function (form) {
      var mode = form.mode;
      if (mode === "manual") {
        return {
          mode: "manual",
          requestedAt: _blankToNull(form.requestedAt),
          relativeTo: null,
          offsetMinutes: null,
        };
      }
      if (mode === "relative") {
        return {
          mode: "relative",
          requestedAt: null,
          relativeTo: _blankToNull(form.relativeTo),
          offsetMinutes: form.offsetMinutes === "" || form.offsetMinutes === undefined
            ? null
            : parseInt(form.offsetMinutes, 10),
        };
      }
      return {
        mode: "none",
        requestedAt: null,
        relativeTo: null,
        offsetMinutes: null,
      };
    },
    // Reminder → 表单
    reminderToForm: function (json) {
      if (!json || json.mode === "none") {
        return { mode: "none", requestedAt: "", relativeTo: "", offsetMinutes: "" };
      }
      if (json.mode === "manual") {
        return {
          mode: "manual",
          requestedAt: json.requestedAt || "",
          relativeTo: "",
          offsetMinutes: "",
        };
      }
      return {
        mode: "relative",
        requestedAt: "",
        relativeTo: json.relativeTo || "",
        offsetMinutes: json.offsetMinutes === null || json.offsetMinutes === undefined
          ? ""
          : String(json.offsetMinutes),
      };
    },

    // 后端返回的 TimeInfo 是五键（含服务端固定的 timeZone），而输入形状是四键；
    // 比较前必须先归一化，否则键数不同恒判为「已变更」（P10-01）。
    normalizeTimeInfo: function (json) {
      if (!json) return null;
      return {
        rawExpression: json.rawExpression === undefined ? null : json.rawExpression,
        precision: json.precision,
        resolvedValue: json.resolvedValue === undefined ? null : json.resolvedValue,
        status: json.status,
      };
    },

    // Task JSON → 表单初始值
    taskToForm: function (task) {
      return {
        title: task.title,
        startTime: formMapping.timeInfoToForm(task.startTime),
        dueTime: formMapping.timeInfoToForm(task.dueTime),
        requirementsText: (task.requirements || []).join("\n"),
        applicabilityStatus: task.applicability.status,
        applicabilityText: task.applicability.text || "",
        sourceExcerpt: task.sourceExcerpt === null || task.sourceExcerpt === undefined
          ? ""
          : task.sourceExcerpt,
        reminder: formMapping.reminderToForm(task.reminder),
        status: task.status,
      };
    },

    // 表单 + 当前任务 → PATCH 体（省略未变字段；显式 null 清空；嵌套完整替换）
    formToPatchBody: function (form, current) {
      form = form || {};
      current = current || {};
      var body = {};

      if (form.title !== undefined && form.title !== current.title) body.title = form.title;

      var startTime = formMapping.timeInfoFromForm(form.startTime);
      if (!_deepEqual(startTime, formMapping.normalizeTimeInfo(current.startTime))) {
        body.startTime = startTime;
      }

      var dueTime = formMapping.timeInfoFromForm(form.dueTime);
      if (!_deepEqual(dueTime, formMapping.normalizeTimeInfo(current.dueTime))) {
        body.dueTime = dueTime;
      }

      var requirements = String(form.requirementsText === undefined ? "" : form.requirementsText)
        .split("\n")
        .map(function (line) { return line.trim(); })
        .filter(function (line) { return line.length > 0; });
      if (form.requirementsText !== undefined && !_deepEqual(requirements, current.requirements || [])) {
        body.requirements = requirements;
      }

      var applicability = {
        text: form.applicabilityStatus === "not_stated" || form.applicabilityStatus === undefined
          ? null
          : _blankToNull(form.applicabilityText),
        status: form.applicabilityStatus,
      };
      if (form.applicabilityStatus !== undefined && !_deepEqual(applicability, current.applicability)) {
        body.applicability = applicability;
      }

      // 原文片段（O-01）：表单 null 且 current 也为 null → 省略（等值）；
      // 表单 null 而 current 非空 → 提交显式 null（用户清空）。
      // 空串按 null 归一后比较（空字符串不是 null 的替代品）。
      if (form.sourceExcerpt !== undefined) {
        var excerptForm = form.sourceExcerpt === "" ? null : form.sourceExcerpt;
        if (excerptForm !== current.sourceExcerpt) body.sourceExcerpt = excerptForm;
      }

      var reminder = form.reminder === undefined
        ? undefined
        : formMapping.reminderFromForm(form.reminder);
      var currentReminderInput = current.reminder
        ? {
            mode: current.reminder.mode,
            requestedAt: current.reminder.requestedAt,
            relativeTo: current.reminder.relativeTo,
            offsetMinutes: current.reminder.offsetMinutes,
          }
        : null;
      if (reminder !== undefined && !_deepEqual(reminder, currentReminderInput)) {
        body.reminder = reminder;
      }

      if (form.status !== undefined && form.status !== current.status) body.status = form.status;

      return body;
    },

    // ---- 导入/核对专用（T09）----

    // 提取请求：source 恰三键（契约 §4.2）
    buildExtractionPayload: function (originalText, messageDate) {
      return {
        source: {
          kind: "text",
          originalText: originalText,
          messageDate: messageDate ? messageDate : null,
        },
      };
    },

    // 确认请求：source 为 8 键 SourceConfirmationInput（契约 §4.2），由提取响应的七键元数据
    // 与用户粘贴原文拼装（fileName=null、originalText=用户原文）。
    buildConfirmationPayload: function (draftSet, originalText, drafts) {
      var meta = draftSet.source;
      return {
        source: {
          id: meta.id,
          kind: meta.kind,
          originalText: originalText,
          messageDate: meta.messageDate === undefined ? null : meta.messageDate,
          importedAt: meta.importedAt,
          mimeType: meta.mimeType,
          fileName: meta.fileName === undefined ? null : meta.fileName,
          contentSha256: meta.contentSha256,
        },
        confirmedTasks: formMapping.confirmedTasks(drafts),
      };
    },

    // T13：图片确认 source（image 源 originalText 必须为 null），其余与文字路径共用
    buildImageConfirmationPayload: function (draftSet, drafts) {
      var meta = draftSet.source;
      return {
        source: {
          id: meta.id,
          kind: "image",
          originalText: null,
          messageDate: meta.messageDate === undefined ? null : meta.messageDate,
          importedAt: meta.importedAt,
          mimeType: meta.mimeType,
          fileName: meta.fileName === undefined ? null : meta.fileName,
          contentSha256: meta.contentSha256,
        },
        confirmedTasks: formMapping.confirmedTasks(drafts),
      };
    },

    // T13：图片提取的 multipart 字段（file 必带；messageDate 为空则省略，避免后端 400）
    buildImageExtractionFields: function (file, messageDate) {
      var fields = [["file", file]];
      if (messageDate) fields.push(["messageDate", messageDate]);
      return fields;
    },

    // T13：文字/截图互斥规则（纯函数）：有文件 → 图片模式，否则文字模式
    importMode: function (hasFile) {
      return hasFile ? "image" : "text";
    },

    // 确认任务项（契约 §4.2 八键）：时间对象只回传四键，timeZone 由服务端固定
    confirmedTasks: function (drafts) {
      return (drafts || []).map(function (d) {
        return {
          draftId: d.id,
          title: d.title,
          startTime: formMapping.normalizeTimeInfo(d.startTime),
          dueTime: formMapping.normalizeTimeInfo(d.dueTime),
          requirements: d.requirements || [],
          applicability: {
            text: d.applicability.text === undefined ? null : d.applicability.text,
            status: d.applicability.status,
          },
          sourceExcerpt: d.sourceExcerpt === undefined ? null : d.sourceExcerpt,
          reminder: {
            mode: d.reminder.mode,
            requestedAt: d.reminder.requestedAt === undefined ? null : d.reminder.requestedAt,
            relativeTo: d.reminder.relativeTo === undefined ? null : d.reminder.relativeTo,
            offsetMinutes: d.reminder.offsetMinutes === undefined ? null : d.reminder.offsetMinutes,
          },
        };
      });
    },
  };

  function _deepEqual(a, b) {
    if (a === b) return true;
    if (a === null || b === null || typeof a !== "object" || typeof b !== "object") {
      return a === b;
    }
    var ak = Object.keys(a);
    var bk = Object.keys(b);
    if (ak.length !== bk.length) return false;
    for (var i = 0; i < ak.length; i++) {
      var key = ak[i];
      if (!Object.prototype.hasOwnProperty.call(b, key)) return false;
      if (!_deepEqual(a[key], b[key])) return false;
    }
    return true;
  }

  // ============================================================== 视图（DOM）
  // 以下仅在浏览器环境执行；node 测试不加载本区。

  var app = scope.querySelector("#app");

  var state = {
    filter: "all",
    search: "",
    importTab: "image",
    tasks: [],
    loading: false,
    detail: null,
    detailSource: null,
    deleteTarget: null,
    deleteTrigger: null,
    deleting: false,
    form: null,
    saving: false,
    // T09：导入与核对（不持久化，刷新即失＝契约语义）
    draftSet: null,
    drafts: [],
    originalText: "",
    extracting: false,
    confirming: false,
    confirmationAttempt: null,
    // T13：截图导入（File 对象留在内存，供确认时重传原图；预览用本地 blob URL）
    file: null,
    filePreviewUrl: null,
    filePreviewToken: 0,
    // 期6-A：待办清单页月历。selectedDate 为 YYYY-MM-DD（null = 不按日期筛选）；
    // scope 为 all / unscheduled，与 selectedDate 互斥（选日期时自动回到 all）。
    calendar: (function () {
      var today = shanghaiTimestamp(new Date()).slice(0, 10);
      return {
        year: Number(today.slice(0, 4)),
        month: Number(today.slice(5, 7)) - 1,
        selectedDate: null,
        scope: "all",
      };
    })(),
    // 期6-B：长期任务（目标）。goals 为进行中的目标列表；goalProgress 缓存每个目标的
    // progress（详情接口带 progress 时优先，否则按关联待办在前端统计）；goalDetail 为
    // 当前打开的详情抽屉数据；toastTimer 用于模块内轻提示的自动隐藏。
    // 期6-C：goalPlan 保存 AI 规划预览状态（独立于抽屉，关闭再打开仍可继续确认）。
    goals: [],
    goalsLoading: false,
    goalProgress: {},
    goalDetail: null,
    goalPlan: { goalId: null, status: "idle", drafts: [], planRevision: 0, suggestedTargetDate: null, error: null, saving: false, saveError: null },
    goalOccurrencesLoading: null,
    toastTimer: null,
  };

  function el(id) {
    return scope.querySelector("#" + id);
  }

  function showError(error) {
    var panel = el("error-panel");
    if (!panel) return;
    panel.innerHTML = "";
    if (!error) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    var title = document.createElement("strong");
    title.textContent = error.message || "请求失败。";
    panel.appendChild(title);
    if (error.fieldErrors && error.fieldErrors.length) {
      var list = document.createElement("ul");
      error.fieldErrors.forEach(function (fe) {
        var item = document.createElement("li");
        item.textContent = fe.field + "：" + (fe.message || fe.code);
        list.appendChild(item);
      });
      panel.appendChild(list);
    }
    if (error.status === 0) {
      var retry = document.createElement("button");
      retry.type = "button";
      retry.textContent = "重试";
      retry.addEventListener("click", function () {
        location.reload();
      });
      panel.appendChild(retry);
    }
  }

  function clearError() {
    showError(null);
  }

  // ============================================================== 提醒弹层（T15）
  // 无 DOM 依赖的纯逻辑区：轮询状态机（依赖注入）、去重、确认分支映射。
  // 仅"打开期间"提醒：不做系统通知/声音/关闭期间提醒/历史补发（契约排除）。

  var reminderLayer = {
    // 去重键：taskId + reminderVersion（契约 §6）
    dedupeKey: function (taskId, version) {
      return String(taskId) + ":" + String(version);
    },

    shouldShow: function (store, item) {
      var key = reminderLayer.dedupeKey(item.taskId, item.reminderVersion);
      return !store.get(key);
    },

    markShown: function (store, item) {
      store.set(reminderLayer.dedupeKey(item.taskId, item.reminderVersion), "1");
    },

    // 确认结果 → 动作分支（200 关层 / 失败未知 / 版本或状态失效刷新后关层）
    // 契约 §4.3：旧版本不得被冒充为原请求成功 → 版本冲突/会话取代/不可确认，
    // 均刷新该任务当前状态后关层（不伪装成功）；仅网络错误与 5xx 保留"结果未知"。
    mapAckResult: function (result) {
      var status = result && result.status;
      var code = result && result.code;
      if (status === 200) return { action: "close", retryable: false };
      if (
        code === "reminder_not_acknowledgeable" ||
        code === "reminder_version_conflict" ||
        code === "reminder_session_superseded" ||
        code === "reminder_session_not_found" ||
        code === "task_not_found"
      ) {
        return { action: "refresh", retryable: false };
      }
      // 网络错误、5xx、其它未知码：不伪装成功
      return { action: "unknown", retryable: true };
    },

    // 轮询状态机：会话只在 start 时创建一次；隐藏时不执行轮询；
    // 409/404 表示会话失效 → 重建会话（契约 §6/§4.3）。
    createReminderPoller: function (deps) {
      var api = deps.api;
      var visibility = deps.visibility || { isHidden: function () { return false; } };
      var onDue = deps.onDue || function () {};
      var onSessionLost = deps.onSessionLost || function () {};
      var state = { session: null, interval: 5, stopped: false };

      async function openSession() {
        state.session = await api.openSession();
        state.interval = state.session && state.session.intervalSeconds
          ? state.session.intervalSeconds
          : 5;
      }

      async function tick() {
        if (state.stopped) return;
        if (visibility.isHidden()) return;           // 隐藏 → 暂停（不重建会话）
        try {
          var data = await api.due(state.session ? state.session.sessionId : null);
          var items = (data && data.reminders) || [];
          if (items.length) onDue(items);            // 空轮询 → 不触发任何回调
        } catch (e) {
          var lost = e && (e.status === 404 || e.status === 409);
          if (lost) {
            onSessionLost();
            await openSession();                     // 重建会话
          } else {
            throw e;
          }
        }
      }

      return {
        start: async function () {
          await openSession();
        },
        tick: tick,
        stop: function () { state.stopped = true; },
        intervalSeconds: function () { return state.interval; },
        sessionId: function () { return state.session ? state.session.sessionId : null; },
      };
    },
  };

  // ============================================================== 文案与视图小工具
  // 模型失败分型文案集中一处（契约 §5 错误码 → 用户可读文案）
  var MODEL_ERROR_TEXT = {
    model_unavailable: "模型服务暂不可用，请稍后重试。",
    extraction_timeout: "提取超时，请重试（长文本可先精简后再试）。",
    model_output_invalid: "模型返回的内容无法解析，请重试。",
    draft_validation_failed: "模型生成的待办字段不合法，请重试。",
    invalid_request: "请求格式不正确，请检查输入。",
    network_error: "无法连接本地服务，请检查服务是否已启动。",
    // T13：截图导入的校验/回看文案
    source_too_large: "截图超过 20 MiB，请压缩后再试。",
    unsupported_media_type: "只支持 PNG 或 JPEG 截图。",
    source_unreadable: "截图无法读取（可能已损坏），请换一张。",
    source_content_missing: "原图缺失，无法回看。",
    source_content_mismatch: "原图与确认内容不一致，请重新选择截图后再试。",
    empty_confirmation: "请至少保留一条待办再保存。",
  };

  // 原生日期控件只显示本地值；接口仍使用既有的 +08:00 时间契约。
  function toLocalInput(value) {
    return (value || "").replace(/\+08:00$/, "");
  }

  function toApiTime(value) {
    if (!value || value.indexOf("T") < 0 || /[Zz]|[+-]\d\d:\d\d$/.test(value)) return value;
    return value + (value.length === 16 ? ":00" : "") + "+08:00";
  }

  function fillDatePicker(input, value) {
    input._apiTime = value || "";
    var local = toLocalInput(value);
    // 浏览器时间控件最多接受毫秒；显示时截取，原始精度留到用户真正改动为止。
    input.value = local.replace(/(\.\d{3})\d+$/, "$1");
    input._shownTime = input.value;
  }

  function readDatePicker(input) {
    return input._shownTime === input.value ? input._apiTime : toApiTime(input.value);
  }

  function readableTime(value) {
    if (!value) return "";
    return toLocalInput(value).replace("T", " ").slice(0, 16);
  }

  function textNode(tag, className, value) {
    var node = document.createElement(tag);
    node.className = className || "";
    node.textContent = value;
    return node;
  }

  function pendingMessages(draft) {
    var messages = [];
    [["startTime", "开始时间"], ["dueTime", "截止时间"]].forEach(function (item) {
      var info = draft[item[0]];
      if (info && info.status === "needs_confirmation") messages.push(item[1] + "尚不明确，请核对原文或补充具体时间。");
    });
    if (draft.applicability && draft.applicability.status === "needs_confirmation") messages.push("请确认这条通知是否适用于你。");
    if (!draft.sourceExcerpt) messages.push("缺少对应原文，请核对来源。");
    return messages;
  }

  function shanghaiTimestamp(date) {
    return new Date(date.getTime() + 8 * 60 * 60 * 1000).toISOString().slice(0, 19) + "+08:00";
  }

  function refreshAutomaticReminder(draft, now) {
    if (!draft._automaticReminder || draft._automaticReminderFrozen) return;
    now = now || new Date();
    var references = ["startTime", "dueTime"].map(function (key) {
      var info = draft[key];
      if (!info || info.status !== "resolved" || info.precision !== "datetime") return null;
      var moment = new Date(info.resolvedValue).getTime();
      return moment > now.getTime() ? {key:key, moment:moment, value:info.resolvedValue} : null;
    }).filter(Boolean).sort(function (a,b) { return a.moment - b.moment; });
    var base = references[0];
    var reminder = {mode:"manual", requestedAt:shanghaiTimestamp(new Date(now.getTime() + 60 * 60 * 1000)), relativeTo:null, offsetMinutes:null,
      scheduledAt:null, state:"not_set", acknowledgedAt:null, revision:null};
    draft._reminderDefaultText = "默认保存 1 小时后提醒，可自行调整。";
    if (base && base.moment - now.getTime() > 31 * 60 * 1000) {
      reminder.mode = "relative"; reminder.requestedAt = null; reminder.relativeTo = base.key === "startTime" ? "start" : "due"; reminder.offsetMinutes = 30;
      draft._reminderDefaultText = "已自动设置：" + (base.key === "startTime" ? "开始" : "截止") + "前 30 分钟提醒。";
    } else if (base) {
      reminder.requestedAt = base.value;
      draft._reminderDefaultText = "事项即将开始或截止，已自动设置到点提醒。";
    }
    draft.reminder = reminder;
  }

  function resolvePartialDate(info, referenceDate) {
    if (!info || info.status !== "needs_confirmation" || info.resolvedValue) return info;
    var raw = info.rawExpression || "";
    if (/某天|暂定|待定|另行通知|不确定|每|[?？]|至|到|~|～|[-—–]|周|星期|\d[:：]\d|\d[点时]/.test(raw)) return info;
    if ((raw.match(/\d{1,2}月\d{1,2}/g) || []).length > 1) return info;
    var date = null;
    var match = raw.match(/(?:(\d{4})年)?(\d{1,2})月(\d{1,2})(?:日|号)/);
    if (match) {
      var year = Number(match[1] || referenceDate.slice(0,4));
      var month = Number(match[2]); var day = Number(match[3]);
      var parsed = new Date(Date.UTC(year, month - 1, day));
      if (parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day) date = parsed.toISOString().slice(0,10);
    } else {
      var relative = raw.match(/今天|明天|后天/);
      if (relative) {
        var delta = {"今天":0,"明天":1,"后天":2}[relative[0]];
        date = shanghaiTimestamp(new Date(new Date(referenceDate + "T00:00:00+08:00").getTime() + delta * 86400000)).slice(0,10);
      }
    }
    if (!date) return info;
    return {rawExpression:raw, precision:"date", resolvedValue:date, status:"resolved", timeZone:"Asia/Shanghai"};
  }

  function prepareCaptureDraft(original, now, referenceDate) {
    var draft = JSON.parse(JSON.stringify(original));
    now = now || new Date();
    referenceDate = referenceDate || shanghaiTimestamp(now).slice(0,10);
    draft.startTime = resolvePartialDate(draft.startTime, referenceDate);
    draft.dueTime = resolvePartialDate(draft.dueTime, referenceDate);
    if (!draft.startTime) {
      draft.startTime = {rawExpression:null, precision:"date", resolvedValue:shanghaiTimestamp(now).slice(0,10), status:"resolved", timeZone:"Asia/Shanghai"};
      draft._defaultStart = true;
    }
    draft._automaticReminder = !draft.reminder || draft.reminder.mode === "none";
    refreshAutomaticReminder(draft, now);
    return draft;
  }

  function updateDetailReminder() {
    var mode = el("f-rem-mode");
    if (!mode) return;
    var manual = el("manual-reminder-field");
    var relative = el("relative-reminder-fields");
    if (manual) manual.hidden = mode.value !== "manual";
    if (relative) relative.hidden = mode.value !== "relative";
  }

  function updateImportPresentation() {
    if (!app) return;
    var imageMode = state.importTab === "image";
    [["tab-shot", imageMode], ["tab-text", !imageMode]].forEach(function (item) {
      var button = el(item[0]);
      button.className = "import-tab" + (item[1] ? " is-active" : "");
      button.setAttribute("aria-selected", String(item[1]));
      button.disabled = state.extracting;
    });
    el("panel-shot").hidden = !imageMode;
    el("panel-text").hidden = imageMode;
    el("dropzone").hidden = !!state.file;
    el("file-actions").hidden = !state.file;
    el("text-count").textContent = el("import-text").value.length + " 字";
    el("extract-loading").hidden = !state.extracting;
    var ready = imageMode ? !!state.file : !!el("import-text").value.trim();
    el("btn-extract").disabled = state.extracting || !ready;
    el("btn-extract").textContent = state.extracting ? "正在提取…" : "提取待办";
    el("import-hint").textContent = ready ? "准备好后，提取并核对任务。" : "请先上传截图或粘贴通知文字。";
    el("import-text").disabled = state.extracting || !!state.file;
    ["import-file", "import-date", "btn-clear-file", "btn-change-file"].forEach(function (id) { el(id).disabled = state.extracting; });
  }

  function switchImportTab(mode) {
    if (state.extracting) return;
    state.importTab = mode;
    if (mode === "text" && state.file) importView.clearFile();
    updateImportPresentation();
  }

  function openImage(url, title) {
    var overlay = document.createElement("dialog");
    overlay.className = "image-lightbox";
    overlay.setAttribute("aria-label", title || "查看原图");
    var image = document.createElement("img"); image.src = url; image.alt = title || "原始截图";
    var close = textNode("button", "", "关闭原图"); close.type = "button";
    overlay.appendChild(image); overlay.appendChild(close); scope.appendChild(overlay);
    function dismiss() { overlay.close(); overlay.remove(); }
    close.addEventListener("click", dismiss);
    overlay.addEventListener("click", function (event) { if (event.target === overlay) dismiss(); });
    overlay.addEventListener("cancel", function (event) { event.preventDefault(); dismiss(); });
    overlay.showModal(); close.focus();
  }

  var viewHelpers = {
    toLocalInput: toLocalInput,
    toApiTime: toApiTime,
    prepareCaptureDraft: prepareCaptureDraft,
    refreshAutomaticReminder: refreshAutomaticReminder,
    // P10-04：时间列同时考虑 startTime 与 dueTime，都无才显示「无时间」
    timeColumnLabel: function (task) {
      var start = task.startTime;
      var due = task.dueTime;
      if (start && due) {
        return "开始 " + timeLabel(start) + " / 截止 " + timeLabel(due);
      }
      if (due) return "截止 " + timeLabel(due);
      if (start) return "开始 " + timeLabel(start);
      return "无时间";
    },

    // 列表行渲染：抽为可测函数（行数应等于任务数；P15-01 类缺陷由 DOM 断言捕获）
    renderTaskRows: function (container, tasks) {
      (tasks || []).forEach(function (task) {
        var row = document.createElement("article");
        row.className = "task-row status-" + task.status;
        var check = textNode("button", "task-check", "");
        check.type = "button";
        check.setAttribute("aria-label", (task.status === "completed" ? "重新打开：" : "标为完成：") + task.title);
        check.addEventListener("click", async function () {
          check.disabled = true;
          try {
            await apiClient.patchTask(task.id, {status: task.status === "completed" ? "open" : "completed"});
            await loadList();
            // 期6-B：任务完成状态会影响目标进度，顺带刷新长期任务卡。
            if (state.goals.length) loadGoals();
          } catch (error) { showError(error); check.disabled = false; }
        });
        if (task.status === "completed") check.innerHTML = '<svg class="icon"><use href="#t-i-checklist"/></svg>';
        var main = document.createElement("a");
        main.className = "task-main";
        main.href = "#/tasks/" + task.id;
        var title = document.createElement("span");
        title.className = "task-title";
        title.textContent = task.title;

        var time = document.createElement("span");
        time.className = "task-time";
        time.textContent = viewHelpers.timeColumnLabel(task);

        var badge = document.createElement("span");
        badge.className = "badge reminder-" + task.reminder.state;
        badge.textContent = reminderBadge(task.reminder);

        main.appendChild(title);
        main.appendChild(time);
        if (task.requirements && task.requirements.length) main.appendChild(textNode("span", "task-requirements", "要求：" + task.requirements.join(" · ")));
        if (task.reviewIssues && task.reviewIssues.length) main.appendChild(textNode("span", "badge needs-review", "有待补充信息"));
        if (task.sourceExcerpt) main.appendChild(textNode("span", "task-source", "原文：" + task.sourceExcerpt));
        var end = document.createElement("div");
        end.className = "task-row-end";
        var detailLink = document.createElement("a");
        detailLink.className = "task-detail-link";
        detailLink.href = "#/tasks/" + task.id;
        detailLink.textContent = "查看详情";
        end.appendChild(badge);
        end.appendChild(detailLink);
        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "task-row-delete";
        remove.setAttribute("aria-label", "删除待办：" + task.title);
        remove.title = "删除待办";
        remove.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#t-i-trash"/></svg>';
        remove.addEventListener("click", function (event) {
          event.preventDefault();
          event.stopPropagation();
          openDeleteDialog(task, remove);
        });
        row.appendChild(check);
        row.appendChild(main);
        row.appendChild(end);
        row.appendChild(remove);
        container.appendChild(row);
      });
      return container;
    },
  };

  function reminderBadge(reminder) {
    if (!reminder) return "";
    var map = {
      not_set: "未设置",
      blocked: "待确认",
      scheduled: "已设置",
      acknowledged: "已确认",
      expired: "已过期",
      cancelled: "已取消",
    };
    return map[reminder.state] || reminder.state;
  }

  function timeLabel(info) {
    if (!info) return "无时间";
    if (info.status === "needs_confirmation") {
      return (info.rawExpression || "待核对") + "（待核对）";
    }
    if (info.resolvedValue) return readableTime(info.resolvedValue);
    return info.rawExpression || "无时间";
  }

  // 期6-A：列表的过滤维度（状态 / 搜索 / 月历日期）各自独立；月历渲染见下方月历区。
  function statusMatchesFilter(task) {
    return state.filter === "all" || task.status === state.filter;
  }

  function calendarMatchesFilter(task) {
    var cal = state.calendar;
    var key = dateKeyOf(task);
    if (cal.scope === "unscheduled") return !key;
    if (cal.selectedDate) return key === cal.selectedDate;
    return true;
  }

  function taskMatchesList(task, query) {
    if (!statusMatchesFilter(task) || !calendarMatchesFilter(task)) return false;
    return !query || task.title.toLocaleLowerCase().indexOf(query) >= 0;
  }

  function listSummaryText(count) {
    var filterLabel = { all: "全部任务", open: "未完成", completed: "已完成" }[state.filter];
    var cal = state.calendar;
    var context = "";
    if (cal.scope === "unscheduled") context = "未安排时间 · ";
    else if (cal.selectedDate) context = calendarDateLabel(cal.selectedDate) + " · ";
    return "当前 " + count + " 条待办 · " + context + filterLabel;
  }

  // 空状态按「搜索 / 某一天 / 未安排 / 确实没有任务」给出不同引导，避免被误认为数据丢失。
  function renderListEmpty(container, query) {
    var cal = state.calendar;
    var title = "这里还没有待办";
    var hint = "上传通知截图或粘贴文字，把要做的事整理到这里。";
    var showImport = true;
    if (query) {
      title = "没有找到匹配的待办";
      hint = "换个关键词，或清空搜索框查看任务。";
      showImport = false;
    } else if (cal.scope === "unscheduled") {
      title = "没有未安排的待办";
      hint = "带日期的待办会显示在月历里，点「全部」可以查看全部任务。";
      showImport = false;
    } else if (cal.selectedDate) {
      title = "这一天没有待办";
      hint = "再点一次选中的日期，或点「全部」恢复显示全部待办。";
      showImport = false;
    }
    container.innerHTML = "";
    var empty = document.createElement("div");
    empty.className = "empty";
    var iconWrap = document.createElement("span");
    iconWrap.className = "upload-icon";
    iconWrap.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#t-i-checklist"/></svg>';
    empty.appendChild(iconWrap);
    empty.appendChild(textNode("h2", "", title));
    empty.appendChild(textNode("p", "", hint));
    if (showImport) {
      var link = document.createElement("a");
      link.className = "btn btn-primary";
      link.href = "#/import";
      link.textContent = "导入通知";
      empty.appendChild(link);
    }
    container.appendChild(empty);
  }

  function renderList() {
    var container = el("task-list");
    if (!container) return;
    // 月历先渲染：即使列表正在加载，日期格与筛选按钮也保持可用。
    renderCalendar();
    container.innerHTML = "";

    if (state.loading) {
      container.innerHTML = '<p class="empty">加载中…</p>';
      return;
    }
    var query = state.search.trim().toLocaleLowerCase();
    var tasks = state.tasks.filter(function (task) { return taskMatchesList(task, query); });
    scope.querySelectorAll("[data-filter]").forEach(function (button) {
      var selected = button.getAttribute("data-filter") === state.filter;
      button.className = "filter-btn" + (selected ? " is-active" : "");
      button.setAttribute("aria-selected", String(selected));
    });
    var summary = el("list-summary");
    if (summary) summary.textContent = listSummaryText(tasks.length);
    if (!tasks.length) {
      renderListEmpty(container, query);
      return;
    }
    viewHelpers.renderTaskRows(container, tasks);
  }

  async function loadList() {
    state.loading = true;
    renderList();
    clearError();
    try {
      // 期6-A：列表与月历共用一次全量拉取（status=all），状态筛选改在前端完成。
      // 月历要跨状态统计每天任务数，若按 state.filter 拉取，切「未完成/已完成」
      // 时会丢掉其它状态的日期数据。
      var data = await apiClient.listTasks("all");
      state.tasks = data.tasks || [];
      var count = el("nav-count");
      if (count && state.filter !== "completed") count.textContent = state.tasks.filter(function (task) { return task.status === "open"; }).length;
    } catch (e) {
      state.tasks = [];
      showError(e);
    }
    state.loading = false;
    renderList();
  }

  // ---------------- 期6-A：待办清单月历 ----------------
  // 月视图数据全部来自 state.tasks（一次 status=all 拉取，前端分组）：
  // 日期归属 dueTime.resolvedValue 优先，其次 startTime.resolvedValue，都没有 → 未安排。
  // 不新增后端请求；后端 from/to 参数就绪后可后续切换，不影响本实现。
  var CALENDAR_DAY_NAMES = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function shanghaiToday() {
    return shanghaiTimestamp(new Date()).slice(0, 10);
  }

  function parseDateKey(key) {
    var match = /^(\d{4})-(\d{2})-(\d{2})/.exec(key || "");
    if (!match) return null;
    return { year: Number(match[1]), month: Number(match[2]) - 1, day: Number(match[3]) };
  }

  function formatDateKey(year, month, day) {
    return year + "-" + pad2(month + 1) + "-" + pad2(day);
  }

  function dateKeyOf(task) {
    if (!task) return null;
    if (task.dueTime && task.dueTime.resolvedValue) return String(task.dueTime.resolvedValue).slice(0, 10);
    if (task.startTime && task.startTime.resolvedValue) return String(task.startTime.resolvedValue).slice(0, 10);
    return null;
  }

  function weekdayOfDateKey(key) {
    var parsed = parseDateKey(key);
    if (!parsed) return 0;
    return new Date(Date.UTC(parsed.year, parsed.month, parsed.day)).getUTCDay();
  }

  // 逾期：未完成且截止时间已过（仅日期时按天比较；无 resolvedValue 不算逾期）。
  function taskIsOverdue(task) {
    if (!task || task.status !== "open" || !task.dueTime) return false;
    var due = task.dueTime.resolvedValue;
    if (!due) return false;
    if (String(due).length > 10) return new Date(due).getTime() < Date.now();
    return String(due).slice(0, 10) < shanghaiToday();
  }

  // 圆点颜色与列表图例一致：已完成 / 逾期 / 待补充 / 普通。
  function taskDotClass(task) {
    if (task.status === "completed") return "is-done";
    if (taskIsOverdue(task)) return "is-overdue";
    if (task.reviewIssues && task.reviewIssues.length) return "is-review";
    return "";
  }

  function calendarDateLabel(key) {
    var parsed = parseDateKey(key);
    if (!parsed) return key || "";
    return (parsed.month + 1) + " 月 " + parsed.day + " 日 " + CALENDAR_DAY_NAMES[weekdayOfDateKey(key)];
  }

  function calendarGroupTasks() {
    var byDate = {};
    var unscheduled = [];
    state.tasks.forEach(function (task) {
      var key = dateKeyOf(task);
      if (!key) {
        unscheduled.push(task);
        return;
      }
      if (!byDate[key]) byDate[key] = [];
      byDate[key].push(task);
    });
    return { byDate: byDate, unscheduled: unscheduled };
  }

  function renderCalendarDay(key, day, dayTasks, flags) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "cal-day" +
      (flags.inMonth ? "" : " is-outside") +
      (key === flags.today ? " is-today" : "") +
      (key === flags.selected ? " is-selected" : "");
    button.setAttribute("data-cal-date", key);
    button.setAttribute("aria-pressed", key === flags.selected ? "true" : "false");
    var parsed = parseDateKey(key);
    var label = parsed.year + "年" + (parsed.month + 1) + "月" + parsed.day + "日 " + CALENDAR_DAY_NAMES[weekdayOfDateKey(key)];
    if (!dayTasks.length) {
      label += "，无待办";
    } else {
      label += "，共 " + dayTasks.length + " 条待办";
      var overdue = dayTasks.filter(taskIsOverdue).length;
      if (overdue) label += "，其中 " + overdue + " 条逾期";
    }
    if (key === flags.today) label += "，今天";
    if (key === flags.selected) label += "，已选中";
    button.setAttribute("aria-label", label);
    button.appendChild(textNode("span", "cal-day-num", String(day)));
    if (dayTasks.length) {
      var dots = document.createElement("span");
      dots.className = "cal-day-dots";
      dots.setAttribute("aria-hidden", "true");
      dayTasks.slice(0, 3).forEach(function (task) {
        var dot = document.createElement("span");
        dot.className = "cal-dot " + taskDotClass(task);
        dots.appendChild(dot);
      });
      // 超过 3 条用 +N 收尾，避免日期格被圆点撑高
      if (dayTasks.length > 3) dots.appendChild(textNode("span", "cal-more", "+" + (dayTasks.length - 3)));
      button.appendChild(dots);
    }
    return button;
  }

  function renderCalendar() {
    var grid = el("cal-grid");
    if (!grid) return;
    var cal = state.calendar;
    var todayKey = shanghaiToday();
    var grouped = calendarGroupTasks();
    var monthPrefix = cal.year + "-" + pad2(cal.month + 1);
    var monthTasks = [];
    Object.keys(grouped.byDate).forEach(function (key) {
      if (key.slice(0, 7) === monthPrefix) monthTasks = monthTasks.concat(grouped.byDate[key]);
    });
    var overdueCount = monthTasks.filter(taskIsOverdue).length;

    var title = el("cal-title");
    if (title) title.textContent = cal.year + " 年 " + (cal.month + 1) + " 月";
    var summary = el("cal-summary");
    if (summary) {
      var summaryText = "本月 " + monthTasks.length + " 条待办";
      if (overdueCount) summaryText += " · 逾期 " + overdueCount + " 条";
      summaryText += " · 未安排 " + grouped.unscheduled.length + " 条";
      summary.textContent = summaryText;
    }

    // 周一开始排 6 行（固定 42 格），切月时高度不跳动。
    var offset = (weekdayOfDateKey(monthPrefix + "-01") + 6) % 7;
    var start = new Date(Date.UTC(cal.year, cal.month, 1 - offset));
    var fragment = document.createDocumentFragment();
    for (var i = 0; i < 42; i += 1) {
      var date = new Date(start.getTime() + i * 86400000);
      var year = date.getUTCFullYear();
      var month = date.getUTCMonth();
      var day = date.getUTCDate();
      var key = formatDateKey(year, month, day);
      fragment.appendChild(renderCalendarDay(key, day, grouped.byDate[key] || [], {
        today: todayKey,
        selected: cal.selectedDate,
        inMonth: year === cal.year && month === cal.month,
      }));
    }
    grid.replaceChildren(fragment);

    scope.querySelectorAll("[data-cal-scope]").forEach(function (button) {
      var active = button.getAttribute("data-cal-scope") === cal.scope;
      button.className = "filter-btn" + (active ? " is-active" : "");
      button.setAttribute("aria-selected", String(active));
    });
    var selection = el("cal-selection");
    if (selection) {
      var selectionText = "当前：全部任务 · " + state.tasks.length + " 条";
      if (cal.scope === "unscheduled") {
        selectionText = "当前：未安排时间 · " + grouped.unscheduled.length + " 条";
      } else if (cal.selectedDate) {
        selectionText = "当前：" + calendarDateLabel(cal.selectedDate) + " · " + (grouped.byDate[cal.selectedDate] || []).length + " 条";
      }
      selection.textContent = selectionText;
    }
  }

  function shiftCalendarMonth(delta) {
    var cal = state.calendar;
    var index = cal.year * 12 + cal.month + delta;
    cal.year = Math.floor(index / 12);
    cal.month = index % 12;
    renderCalendar();
  }

  // 点某一天：选中并把列表筛到那天；再点同一天取消。
  function selectCalendarDate(key) {
    var cal = state.calendar;
    // 网格会整体重建，从键盘触发时把焦点还给同一个日期格。
    var hadFocus = !!(document.activeElement && document.activeElement.closest && document.activeElement.closest("#cal-grid"));
    if (cal.scope === "all" && cal.selectedDate === key) {
      cal.selectedDate = null;
    } else {
      cal.scope = "all";
      cal.selectedDate = key;
      var parsed = parseDateKey(key);
      if (parsed) {
        cal.year = parsed.year;
        cal.month = parsed.month;
      }
    }
    renderList();
    if (hadFocus) {
      var grid = el("cal-grid");
      var cell = grid ? grid.querySelector('[data-cal-date="' + key + '"]') : null;
      if (cell) cell.focus();
    }
  }

  function setCalendarScope(scopeName) {
    var cal = state.calendar;
    cal.scope = scopeName === "unscheduled" ? "unscheduled" : "all";
    cal.selectedDate = null;
    renderList();
  }

  //「回到今天」：视图回到当月并选中今天（再点一次今天即恢复全部）。
  function goCalendarToday() {
    var key = shanghaiToday();
    var cal = state.calendar;
    var parsed = parseDateKey(key);
    if (parsed) {
      cal.year = parsed.year;
      cal.month = parsed.month;
    }
    cal.scope = "all";
    cal.selectedDate = key;
    renderList();
  }

  // ---------------- 期6-B：长期任务（目标） ----------------
  // 契约：GET /api/v1/goals?status=active 返回 {goals:[…]}；GET /goals/{id} 在期3
  // 后端会附带 progress:{total,completed,overdue}；DELETE /goals/{id} 是归档。
  // 若实例还没有 progress 字段，则按 GET /tasks?goalId=… 的关联待办在前端统计，
  // 保证卡片进度始终可显示；关联字段由期3后端补齐后本逻辑自动切换。
  var WEEKDAY_SHORT = ["一", "二", "三", "四", "五", "六", "日"];
  var GOAL_KIND_LABEL = { plan: "计划", habit: "习惯" };

  function formatDateCn(value) {
    var parsed = parseDateKey(value);
    if (!parsed) return value || "";
    return parsed.year + " 年 " + (parsed.month + 1) + " 月 " + parsed.day + " 日";
  }

  function goalKindLabel(goal) {
    return GOAL_KIND_LABEL[goal.kind] || goal.kind;
  }

  // 计划剩余天数（按上海时区日期差）；null = 没有目标日期。
  function goalRemainingDays(goal) {
    if (!goal || !goal.targetDate) return null;
    var target = parseDateKey(goal.targetDate);
    var today = parseDateKey(shanghaiToday());
    if (!target || !today) return null;
    return Math.round(
      (Date.UTC(target.year, target.month, target.day) - Date.UTC(today.year, today.month, today.day)) / 86400000
    );
  }

  function goalRemainingLabel(goal) {
    var days = goalRemainingDays(goal);
    if (days === null) return "";
    if (days > 0) return "还剩 " + days + " 天";
    if (days === 0) return "今天到期";
    return "已过期 " + Math.abs(days) + " 天";
  }

  // 习惯周期文案：每天 / 每周一、三、五 · 20:00 · 30 分钟
  function recurrenceLabel(recurrence) {
    if (!recurrence) return "";
    var parts = [];
    if (recurrence.freq === "weekly") {
      var days = (recurrence.weekdays || [])
        .map(function (day) { return WEEKDAY_SHORT[day - 1] || ""; })
        .filter(Boolean);
      parts.push("每周" + (days.length ? days.join("、") : ""));
    } else {
      parts.push("每天");
    }
    if (recurrence.time) parts.push(recurrence.time);
    if (recurrence.durationMinutes) parts.push(recurrence.durationMinutes + " 分钟");
    return parts.join(" · ");
  }

  function computeProgressFromTasks(tasks) {
    var list = tasks || [];
    return {
      total: list.length,
      completed: list.filter(function (task) { return task.status === "completed"; }).length,
      overdue: list.filter(taskIsOverdue).length,
      source: "tasks",
    };
  }

  function normalizeGoalProgress(progress) {
    if (!progress || typeof progress.total !== "number") return null;
    return {
      total: progress.total,
      completed: Number(progress.completed) || 0,
      overdue: Number(progress.overdue) || 0,
      source: "detail",
    };
  }

  // 卡片进度：优先详情接口的 progress；没有就按 goalId 拉关联待办统计。
  async function fetchGoalProgress(goal) {
    var detail = await apiClient.getGoal(goal.id);
    var fromDetail = normalizeGoalProgress(detail && detail.progress);
    if (fromDetail) return fromDetail;
    try {
      var data = await apiClient.listGoalTasks(goal.id);
      return computeProgressFromTasks(data.tasks || []);
    } catch (e) {
      return { total: 0, completed: 0, overdue: 0, source: "tasks" };
    }
  }

  function goalsSummaryText() {
    if (state.goalsLoading) return "正在读取长期任务…";
    if (!state.goals.length) {
      return "把需要多天推进的计划和每天重复的习惯放在这里，按目标跟踪进度。";
    }
    var plans = state.goals.filter(function (goal) { return goal.kind === "plan"; }).length;
    return "共 " + state.goals.length + " 个进行中的目标 · 计划 " + plans + " 个 · 习惯 " + (state.goals.length - plans) + " 个";
  }

  // 进度条用原生 <progress>（value/max 属性），避免 CSP 禁止的内联 style 宽度。
  function goalProgressBlock(progress) {
    var block = document.createElement("div");
    block.className = "goal-progress";
    if (!progress || !progress.total) {
      block.appendChild(textNode("span", "goal-progress-caption", "暂无关联待办"));
      if (progress && progress.overdue) {
        block.appendChild(textNode("span", "goal-overdue-badge", "逾期 " + progress.overdue));
      }
      return block;
    }
    var line = document.createElement("div");
    line.className = "goal-progress-line";
    line.appendChild(textNode("span", "goal-progress-caption", "已完成 " + progress.completed + " / " + progress.total));
    if (progress.overdue) line.appendChild(textNode("span", "goal-overdue-badge", "逾期 " + progress.overdue));
    block.appendChild(line);
    var meter = document.createElement("progress");
    meter.className = "goal-progress-meter";
    meter.max = progress.total;
    meter.value = Math.min(progress.completed, progress.total);
    meter.setAttribute("aria-label", "目标进度 " + progress.completed + " / " + progress.total);
    block.appendChild(meter);
    return block;
  }

  function goalCardMeta(goal) {
    var meta = document.createElement("div");
    meta.className = "goal-card-meta";
    if (goal.kind === "plan") {
      if (goal.targetDate) {
        var remaining = goalRemainingLabel(goal);
        meta.appendChild(textNode("span", "goal-chip", "目标 " + formatDateCn(goal.targetDate) + (remaining ? " · " + remaining : "")));
      }
      if (goal.dailyCapacity) meta.appendChild(textNode("span", "goal-chip", "每天 " + goal.dailyCapacity + " 条"));
    } else if (goal.recurrence) {
      meta.appendChild(textNode("span", "goal-chip", recurrenceLabel(goal.recurrence)));
    }
    return meta;
  }

  function goalActionButton(label, action, goalId, iconName, variant) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn " + (variant || "btn-secondary") + " btn-small goal-action";
    button.setAttribute("data-goal-action", action);
    button.setAttribute("data-goal-id", goalId);
    if (iconName) {
      // iconName 是代码内常量（t-i-* sprite），不来自用户输入。
      button.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#' + iconName + '"/></svg>';
      button.appendChild(document.createTextNode(label));
    } else {
      button.textContent = label;
    }
    return button;
  }

  function renderGoalCard(goal) {
    var card = document.createElement("article");
    card.className = "goal-card goal-card-" + goal.kind;
    card.setAttribute("data-goal-id", goal.id);
    var head = document.createElement("div");
    head.className = "goal-card-head";
    head.appendChild(textNode("span", "goal-kind goal-kind-" + goal.kind, goalKindLabel(goal)));
    head.appendChild(textNode("h3", "goal-card-title", goal.title));
    card.appendChild(head);
    if (goal.description) card.appendChild(textNode("p", "goal-card-desc", goal.description));
    card.appendChild(goalCardMeta(goal));
    card.appendChild(goalProgressBlock(state.goalProgress[goal.id]));
    var actions = document.createElement("div");
    actions.className = "goal-card-actions";
    actions.appendChild(goalActionButton("查看详情", "detail", goal.id));
    if (goal.kind === "plan") {
      actions.appendChild(goalActionButton("AI 规划", "plan", goal.id, "t-i-sparkles"));
    } else {
      actions.appendChild(goalActionButton("生成未来 14 天", "occurrences", goal.id, "t-i-repeat"));
    }
    actions.appendChild(goalActionButton("归档", "archive", goal.id, "t-i-archive"));
    card.appendChild(actions);
    return card;
  }

  function renderGoals() {
    var container = el("goal-list");
    if (!container) return;
    var summary = el("goals-summary");
    if (summary) summary.textContent = goalsSummaryText();
    container.innerHTML = "";
    if (state.goalsLoading) {
      container.appendChild(textNode("p", "goal-empty", "正在读取长期任务…"));
      return;
    }
    if (!state.goals.length) {
      var empty = document.createElement("div");
      empty.className = "goal-empty";
      empty.appendChild(textNode("strong", "goal-empty-title", "还没有长期任务"));
      empty.appendChild(textNode("p", "goal-empty-text", "「新建计划」用于有明确目标日期的多天任务；「新建习惯」用于每天或每周重复的事。"));
      container.appendChild(empty);
      return;
    }
    state.goals.forEach(function (goal) { container.appendChild(renderGoalCard(goal)); });
  }

  async function loadGoals() {
    if (!el("goal-list")) return;
    state.goalsLoading = true;
    renderGoals();
    try {
      var data = await apiClient.listGoals("active");
      state.goals = data.goals || [];
      var progressMap = {};
      await Promise.all(state.goals.map(async function (goal) {
        try {
          progressMap[goal.id] = await fetchGoalProgress(goal);
        } catch (e) {
          progressMap[goal.id] = { total: 0, completed: 0, overdue: 0, source: "tasks" };
        }
      }));
      state.goalProgress = progressMap;
      clearError();
    } catch (e) {
      state.goals = [];
      state.goalProgress = {};
      showError(e);
    }
    state.goalsLoading = false;
    renderGoals();
  }

  // ---------------- 长期任务详情 ----------------

  function detailMetaRow(label, value) {
    var row = document.createElement("div");
    row.className = "goal-detail-meta-item";
    row.appendChild(textNode("span", "goal-detail-meta-label", label));
    row.appendChild(textNode("span", "goal-detail-meta-value", value));
    return row;
  }

  function renderGoalLinkedTasks(tasks) {
    var section = document.createElement("section");
    section.className = "goal-detail-section";
    section.appendChild(textNode("h2", "goal-detail-heading", "关联待办 · " + tasks.length + " 条"));
    if (!tasks.length) {
      section.appendChild(textNode("p", "goal-detail-empty", "这个目标还没有关联待办。计划型目标可用「AI 规划」生成任务；习惯型目标可生成未来 14 天的实例。"));
      return section;
    }
    var list = document.createElement("div");
    list.className = "goal-linked-tasks";
    tasks.forEach(function (task) {
      var overdue = taskIsOverdue(task);
      var row = document.createElement("a");
      row.className = "goal-linked-task" + (task.status === "completed" ? " is-completed" : "");
      row.href = "#/tasks/" + task.id;
      var main = document.createElement("span");
      main.className = "goal-linked-task-main";
      main.appendChild(textNode("span", "goal-linked-task-title", task.title));
      main.appendChild(textNode("span", "goal-linked-task-meta", viewHelpers.timeColumnLabel(task)));
      row.appendChild(main);
      var badge = document.createElement("span");
      badge.className = "badge " + (task.status === "completed" ? "is-completed" : overdue ? "is-overdue" : "");
      badge.textContent = task.status === "completed" ? "已完成" : overdue ? "逾期" : "未完成";
      row.appendChild(badge);
      list.appendChild(row);
    });
    section.appendChild(list);
    return section;
  }

  function renderGoalDetail() {
    var detail = state.goalDetail;
    if (!detail || !detail.goal) return;
    var goal = detail.goal;
    var progress = detail.progress || { total: 0, completed: 0, overdue: 0 };
    var title = el("goal-drawer-title");
    if (title) title.textContent = goal.title;
    var kind = el("goal-drawer-kind");
    if (kind) {
      kind.className = "goal-kind goal-kind-" + goal.kind;
      kind.textContent = goalKindLabel(goal);
    }
    var statusLabel = goal.status === "active" ? "进行中" : goal.status === "done" ? "已完成" : "已归档";
    var meta = el("goal-drawer-meta");
    if (meta) {
      meta.textContent = "长期任务 · " + statusLabel +
        (goal.createdAt ? " · 创建于 " + formatDateCn(goal.createdAt.slice(0, 10)) : "");
    }
    var content = el("goal-detail-content");
    if (!content) return;
    content.innerHTML = "";
    if (goal.description) content.appendChild(textNode("p", "goal-detail-desc", goal.description));
    var grid = document.createElement("div");
    grid.className = "goal-detail-meta";
    grid.appendChild(detailMetaRow("类型", goalKindLabel(goal)));
    grid.appendChild(detailMetaRow("开始日期", formatDateCn(goal.startDate)));
    if (goal.kind === "plan") {
      var remaining = goalRemainingLabel(goal);
      grid.appendChild(detailMetaRow("目标日期", formatDateCn(goal.targetDate) + (remaining ? "（" + remaining + "）" : "")));
      grid.appendChild(detailMetaRow("每天容量", goal.dailyCapacity ? goal.dailyCapacity + " 条" : "未设置"));
      if (goal.planRevision) grid.appendChild(detailMetaRow("规划轮次", "第 " + goal.planRevision + " 轮"));
    } else {
      grid.appendChild(detailMetaRow("重复周期", recurrenceLabel(goal.recurrence) || "未设置"));
    }
    grid.appendChild(detailMetaRow("进度", progress.total ? progress.completed + " / " + progress.total : "尚无关联待办"));
    content.appendChild(grid);
    content.appendChild(goalProgressBlock(progress));
    content.appendChild(renderGoalLinkedTasks(detail.tasks || []));
    // 期6-C：AI 规划预览（状态独立于抽屉，关掉再打开仍能继续确认）
    var plan = state.goalPlan;
    if (plan && plan.goalId === goal.id) content.appendChild(renderPlanPreview());
    var planning = !!(plan && plan.goalId === goal.id && plan.status === "loading");
    var aiButton = el("btn-goal-ai");
    if (aiButton) {
      aiButton.hidden = goal.kind !== "plan";
      aiButton.disabled = planning;
      aiButton.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#t-i-sparkles"/></svg>' +
        (planning ? "AI 规划中…" : "AI 规划");
    }
    var occurrencesLoading = state.goalOccurrencesLoading === goal.id;
    var occurrencesButton = el("btn-goal-occurrences");
    if (occurrencesButton) {
      occurrencesButton.hidden = goal.kind !== "habit";
      occurrencesButton.disabled = occurrencesLoading;
      occurrencesButton.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#t-i-repeat"/></svg>' +
        (occurrencesLoading ? "正在生成…" : "生成未来 14 天");
    }
  }

  // ---------------- 期6-C：AI 规划预览 / 草稿确认 / 习惯实例 ----------------

  function planErrorText(error) {
    var code = error && error.code;
    if (code === "model_unavailable") return "AI 规划服务暂不可用（可能未配置模型密钥或服务不可用），请稍后再试。";
    if (code === "extraction_timeout") return "AI 规划超时（约 30 秒未返回），请稍后重试。";
    if (code === "model_output_invalid") return "AI 返回的规划内容无法解析，请重试。";
    if (code === "plan_validation_failed") return "AI 返回的规划字段不合法，请重试。";
    if (code === "goal_not_plan") return "只有计划型长期任务可以使用 AI 规划。";
    if (code === "goal_not_found") return "长期任务不存在，可能已被归档。";
    if (code === "network_error" || (error && error.status === 0)) return "无法连接本地服务，请检查服务是否已启动。";
    return (error && error.message) || "AI 规划失败，请重试。";
  }

  function planActionButton(label, action, className) {
    var button = textNode("button", (className || "btn btn-secondary btn-small") + " plan-preview-button", label);
    button.type = "button";
    button.setAttribute("data-plan-action", action);
    return button;
  }

  function renderPlanDraft(draft, index) {
    var item = document.createElement("article");
    item.className = "plan-draft";
    var main = document.createElement("div");
    main.className = "plan-draft-main";
    var top = document.createElement("div");
    top.className = "plan-draft-top";
    top.appendChild(textNode("span", "plan-draft-date", draft.plannedDate ? formatDateCn(draft.plannedDate) : "未定日期"));
    top.appendChild(textNode("strong", "plan-draft-title", draft.title || "未命名任务"));
    main.appendChild(top);
    var metaParts = [];
    metaParts.push(draft.dueTime ? "截止 " + timeLabel(draft.dueTime) : "无截止时间");
    var requirementCount = (draft.requirements || []).length;
    metaParts.push(requirementCount ? "要求 " + requirementCount + " 条" : "无执行要求");
    main.appendChild(textNode("span", "plan-draft-meta", metaParts.join(" · ")));
    item.appendChild(main);
    var removeButton = textNode("button", "plan-draft-remove", "移除");
    removeButton.type = "button";
    removeButton.setAttribute("data-plan-action", "remove");
    removeButton.setAttribute("data-plan-index", String(index));
    removeButton.setAttribute("aria-label", "移除草稿：" + (draft.title || "未命名任务"));
    item.appendChild(removeButton);
    return item;
  }

  function renderPlanPreview() {
    var plan = state.goalPlan;
    var section = document.createElement("section");
    section.className = "plan-preview";
    section.setAttribute("aria-live", "polite");
    if (plan.status === "loading") {
      section.appendChild(textNode("h2", "goal-detail-heading", "规划预览"));
      var loading = document.createElement("div");
      loading.className = "plan-loading";
      var spinner = document.createElement("span");
      spinner.className = "spinner";
      loading.appendChild(spinner);
      var loadingText = document.createElement("div");
      loadingText.appendChild(textNode("strong", "plan-loading-title", "AI 规划中…"));
      loadingText.appendChild(textNode("p", "plan-loading-text", "正在调用模型计算目标区间内的空缺，可能需要 10–30 秒，请稍候。"));
      loading.appendChild(loadingText);
      section.appendChild(loading);
      return section;
    }
    if (plan.status === "error") {
      section.appendChild(textNode("h2", "goal-detail-heading", "规划失败"));
      section.appendChild(textNode("p", "plan-error-message", planErrorText(plan.error)));
      var errorActions = document.createElement("div");
      errorActions.className = "plan-preview-actions";
      errorActions.appendChild(planActionButton("重试", "replan", "btn btn-primary btn-small"));
      errorActions.appendChild(planActionButton("关闭", "dismiss", "btn btn-secondary btn-small"));
      section.appendChild(errorActions);
      return section;
    }
    var drafts = plan.drafts || [];
    section.appendChild(textNode("h2", "goal-detail-heading", "规划预览 · " + drafts.length + " 条"));
    if (plan.suggestedTargetDate) {
      section.appendChild(textNode("p", "plan-preview-hint", "AI 建议目标日期：" + formatDateCn(plan.suggestedTargetDate) + "（可在保存后到目标详情调整）"));
    }
    if (!drafts.length) {
      section.appendChild(textNode("p", "plan-empty-text", "没有需要补的空缺。目标区间内已有任务，或目标日期已过。"));
      var emptyActions = document.createElement("div");
      emptyActions.className = "plan-preview-actions";
      emptyActions.appendChild(planActionButton("重新检查", "replan", "btn btn-secondary btn-small"));
      emptyActions.appendChild(planActionButton("关闭", "dismiss", "btn btn-secondary btn-small"));
      section.appendChild(emptyActions);
      return section;
    }
    var list = document.createElement("div");
    list.className = "plan-draft-list";
    drafts.forEach(function (draft, index) {
      list.appendChild(renderPlanDraft(draft, index));
    });
    section.appendChild(list);
    if (plan.saveError) {
      section.appendChild(textNode("p", "plan-error-message", "保存失败：" + goalErrorMessage(plan.saveError)));
    }
    var footer = document.createElement("div");
    footer.className = "plan-preview-actions";
    var saveButton = planActionButton("保存这些任务（" + drafts.length + "）", "save", "btn btn-primary btn-small");
    saveButton.disabled = !!plan.saving;
    footer.appendChild(saveButton);
    var cancelButton = planActionButton("取消", "dismiss", "btn btn-secondary btn-small");
    cancelButton.disabled = !!plan.saving;
    footer.appendChild(cancelButton);
    section.appendChild(footer);
    return section;
  }

  async function startGoalPlan(goalId) {
    if (!goalId) return;
    var pending = state.goalPlan.goalId === goalId && (state.goalPlan.status === "ready" || state.goalPlan.status === "error");
    if (pending) {
      // 已有未确认的规划结果/失败详情：重新打开抽屉继续确认，避免重复调用模型。
      if (!state.goalDetail || state.goalDetail.id !== goalId) await openGoalDetail(goalId);
      else renderGoalDetail();
      showToast(state.goalPlan.status === "ready" ? "已有未确认的规划预览，请先保存或取消。" : "上次规划失败，可在预览区重试。");
      return;
    }
    if (state.goalPlan.goalId === goalId && state.goalPlan.status === "loading") {
      showToast("AI 规划正在进行中，请稍候。");
      if (!state.goalDetail || state.goalDetail.id !== goalId) openGoalDetail(goalId);
      return;
    }
    if (!state.goalDetail || state.goalDetail.id !== goalId || !state.goalDetail.goal) {
      await openGoalDetail(goalId);
    }
    var detail = state.goalDetail;
    if (!detail || !detail.goal) return;
    if (detail.goal.kind !== "plan") {
      showToast("只有计划型长期任务可以使用 AI 规划。");
      return;
    }
    state.goalPlan = {
      goalId: goalId,
      status: "loading",
      drafts: [],
      planRevision: detail.goal.planRevision || 0,
      suggestedTargetDate: null,
      error: null,
      saving: false,
      saveError: null,
    };
    if (state.goalDetail && state.goalDetail.id === goalId) renderGoalDetail();
    try {
      var result = await apiClient.planGoal(goalId);
      if (state.goalPlan.goalId !== goalId) return;
      state.goalPlan.status = "ready";
      state.goalPlan.drafts = result.drafts || [];
      if (typeof result.planRevision === "number") state.goalPlan.planRevision = result.planRevision;
      state.goalPlan.suggestedTargetDate = result.suggestedTargetDate || null;
      if (state.goalDetail && state.goalDetail.id === goalId && state.goalDetail.goal) {
        state.goalDetail.goal.planRevision = state.goalPlan.planRevision;
        renderGoalDetail();
      }
      if (!state.goalPlan.drafts.length) showToast("AI 规划完成：没有需要补的空缺。");
      else showToast("AI 已生成 " + state.goalPlan.drafts.length + " 条规划草稿，请确认后保存。");
    } catch (e) {
      if (state.goalPlan.goalId !== goalId) return;
      state.goalPlan.status = "error";
      state.goalPlan.error = e;
      if (state.goalDetail && state.goalDetail.id === goalId) renderGoalDetail();
    }
  }

  function removePlanDraft(index) {
    var plan = state.goalPlan;
    if (!plan || plan.status !== "ready") return;
    var position = Number(index);
    if (!isFinite(position) || position < 0 || position >= plan.drafts.length) return;
    plan.drafts.splice(position, 1);
    if (state.goalDetail && state.goalDetail.id === plan.goalId) renderGoalDetail();
  }

  function dismissPlanPreview() {
    state.goalPlan = {
      goalId: null, status: "idle", drafts: [], planRevision: 0,
      suggestedTargetDate: null, error: null, saving: false, saveError: null,
    };
    if (state.goalDetail) renderGoalDetail();
  }

  async function savePlanDrafts() {
    var plan = state.goalPlan;
    if (!plan || plan.status !== "ready" || !plan.drafts.length || plan.saving) return;
    var goalId = plan.goalId;
    var drafts = plan.drafts.slice();
    plan.saving = true;
    plan.saveError = null;
    if (state.goalDetail && state.goalDetail.id === goalId) renderGoalDetail();
    try {
      var result = await apiClient.saveGoalTasks(goalId, drafts, plan.planRevision);
      var savedCount = (result.tasks || []).length;
      showToast("已保存 " + savedCount + " 条规划任务。");
      dismissPlanPreview();
      await refreshGoalDetail(goalId);
      await Promise.all([loadList(), loadGoals()]);
    } catch (e) {
      if (state.goalPlan && state.goalPlan.goalId === goalId) {
        state.goalPlan.saving = false;
        state.goalPlan.saveError = e;
        if (state.goalDetail && state.goalDetail.id === goalId) renderGoalDetail();
      }
    }
  }

  async function generateGoalOccurrences(goalId, trigger) {
    if (!goalId) return;
    if (state.goalOccurrencesLoading === goalId) {
      showToast("习惯实例正在生成中，请稍候。");
      return;
    }
    if (trigger) trigger.disabled = true;
    state.goalOccurrencesLoading = goalId;
    if (state.goalDetail && state.goalDetail.id === goalId) renderGoalDetail();
    try {
      var result = await apiClient.generateGoalOccurrences(goalId);
      var created = result && typeof result.created === "number" ? result.created : 0;
      showToast(created > 0
        ? "已生成 " + created + " 条未来 14 天的习惯实例。"
        : "未来 14 天已是最新，没有新增实例。");
      await refreshGoalDetail(goalId);
      await Promise.all([loadList(), loadGoals()]);
    } catch (e) {
      showError(e);
      showToast(goalActionErrorMessage(e));
    } finally {
      state.goalOccurrencesLoading = null;
      if (trigger && trigger.isConnected) trigger.disabled = false;
      if (state.goalDetail && state.goalDetail.id === goalId) renderGoalDetail();
    }
  }

  function goalActionErrorMessage(error) {
    if (!error) return "操作失败，请重试。";
    if (error.code === "network_error" || error.status === 0) return "无法连接本地服务，请检查服务是否已启动。";
    return error.message || "操作失败，请重试。";
  }

  async function fetchGoalDetailData(goalId) {
    var detail = await apiClient.getGoal(goalId);
    var tasks = [];
    try {
      var data = await apiClient.listGoalTasks(goalId);
      tasks = data.tasks || [];
    } catch (e) {
      tasks = [];
    }
    var progress = normalizeGoalProgress(detail.progress) || computeProgressFromTasks(tasks);
    return { goal: detail.goal, progress: progress, tasks: tasks };
  }

  async function refreshGoalDetail(goalId) {
    if (!state.goalDetail || state.goalDetail.id !== goalId) return;
    try {
      var data = await fetchGoalDetailData(goalId);
      if (!state.goalDetail || state.goalDetail.id !== goalId) return;
      state.goalDetail = { id: goalId, goal: data.goal, progress: data.progress, tasks: data.tasks };
      renderGoalDetail();
    } catch (e) {
      showError(e);
    }
  }

  async function openGoalDetail(goalId) {
    var drawer = el("goal-drawer");
    if (!drawer) return;
    state.goalDetail = { id: goalId, loading: true };
    drawer.hidden = false;
    // 打开后把焦点交给关闭按钮，键盘用户可以立刻 Esc / Enter 退出。
    var closeButton = el("btn-goal-close");
    if (closeButton) closeButton.focus();
    var title = el("goal-drawer-title");
    if (title) title.textContent = "长期任务详情";
    var kind = el("goal-drawer-kind");
    if (kind) { kind.className = "goal-kind"; kind.textContent = ""; }
    var meta = el("goal-drawer-meta");
    if (meta) meta.textContent = "";
    var content = el("goal-detail-content");
    if (content) {
      content.innerHTML = "";
      content.appendChild(textNode("p", "goal-detail-empty", "加载中…"));
    }
    var aiButton = el("btn-goal-ai");
    if (aiButton) aiButton.hidden = true;
    var occurrencesButton = el("btn-goal-occurrences");
    if (occurrencesButton) occurrencesButton.hidden = true;
    try {
      var data = await fetchGoalDetailData(goalId);
      if (state.goalDetail && state.goalDetail.id === goalId) {
        state.goalDetail = { id: goalId, goal: data.goal, progress: data.progress, tasks: data.tasks };
        if (!drawer.hidden) renderGoalDetail();
      }
    } catch (e) {
      if (content) {
        content.innerHTML = "";
        content.appendChild(textNode("p", "goal-detail-error", (e && e.message) || "长期任务加载失败。"));
      }
      showError(e);
    }
  }

  function closeGoalDetail() {
    state.goalDetail = null;
    var drawer = el("goal-drawer");
    if (drawer) drawer.hidden = true;
  }

  // ---------------- 长期任务新建对话框 ----------------

  function showToast(message) {
    var toast = el("tasks-toast");
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    if (state.toastTimer) clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(function () {
      state.toastTimer = null;
      toast.hidden = true;
    }, 3200);
  }

  function hideToast() {
    if (state.toastTimer) { clearTimeout(state.toastTimer); state.toastTimer = null; }
    var toast = el("tasks-toast");
    if (toast) toast.hidden = true;
  }

  function updateHabitWeekdays() {
    var fieldset = el("nh-weekdays");
    var frequency = el("nh-freq");
    if (fieldset && frequency) fieldset.hidden = frequency.value !== "weekly";
  }

  function selectedHabitWeekdays() {
    return Array.prototype.slice
      .call(scope.querySelectorAll("[data-habit-weekday]"))
      .filter(function (checkbox) { return checkbox.checked; })
      .map(function (checkbox) { return Number(checkbox.value); })
      .sort(function (a, b) { return a - b; });
  }

  function goalDialogError(prefix, message) {
    var error = el(prefix + "-error");
    if (!error) return;
    error.textContent = message;
    error.hidden = false;
  }

  // 用户一改动目标表单就收起上一次的校验错误，避免旧错误一直挂在对话框底部。
  function hideGoalDialogError(event) {
    var form = event && event.currentTarget;
    var error = form ? form.querySelector(".dialog-error") : null;
    if (error) error.hidden = true;
  }

  function goalErrorMessage(error) {
    if (!error) return "保存失败，请重试。";
    if (error.fieldErrors && error.fieldErrors.length) {
      var first = error.fieldErrors[0];
      return (error.message || "保存失败。") + "（" + (first.field || "字段") + "：" + (first.message || first.code) + "）";
    }
    return error.message || "保存失败，请重试。";
  }

  function openGoalDialog(kind) {
    closeGoalDetail();
    var dialog = el(kind === "plan" ? "new-plan-dialog" : "new-habit-dialog");
    if (!dialog) return;
    hideToast();
    var form = dialog.querySelector("form");
    if (form) form.reset();
    var error = el(kind === "plan" ? "np-error" : "nh-error");
    if (error) { error.hidden = true; error.textContent = ""; }
    var start = el(kind === "plan" ? "np-start" : "nh-start");
    if (start) start.value = shanghaiToday();
    if (kind === "plan") {
      var target = el("np-target");
      if (target) target.value = "";
      var capacity = el("np-capacity");
      if (capacity) capacity.value = "3";
    } else {
      var frequency = el("nh-freq");
      if (frequency) frequency.value = "daily";
      var time = el("nh-time");
      if (time) time.value = "";
      var duration = el("nh-duration");
      if (duration) duration.value = "";
      scope.querySelectorAll("[data-habit-weekday]").forEach(function (checkbox) { checkbox.checked = false; });
      updateHabitWeekdays();
    }
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    var titleInput = el(kind === "plan" ? "np-title" : "nh-title");
    if (titleInput) titleInput.focus();
  }

  function closeGoalDialog(kind) {
    var dialog = el(kind === "plan" ? "new-plan-dialog" : "new-habit-dialog");
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  async function submitPlan(event) {
    if (event) event.preventDefault();
    var submit = el("np-submit");
    var title = (el("np-title").value || "").trim();
    var startDate = el("np-start").value;
    var targetDate = el("np-target").value;
    var capacity = Number(el("np-capacity").value);
    if (!title) { goalDialogError("np", "请填写目标名称。"); return; }
    if (!startDate) { goalDialogError("np", "请选择开始日期。"); return; }
    // 后端契约：plan 型必须带 targetDate（期2 领域模型校验），因此前端必填。
    if (!targetDate) { goalDialogError("np", "计划需要目标日期（后端要求 plan 必须填写 targetDate）。"); return; }
    if (targetDate < startDate) { goalDialogError("np", "目标日期不能早于开始日期。"); return; }
    if (!capacity || capacity < 1 || capacity > 5) { goalDialogError("np", "每天安排条数需在 1 到 5 之间。"); return; }
    var payload = {
      kind: "plan",
      title: title,
      startDate: startDate,
      targetDate: targetDate,
      dailyCapacity: capacity,
    };
    var description = (el("np-description").value || "").trim();
    if (description) payload.description = description;
    var error = el("np-error");
    if (error) error.hidden = true;
    if (submit) submit.disabled = true;
    try {
      await apiClient.createGoal(payload);
      closeGoalDialog("plan");
      await loadGoals();
      showToast("已新建计划：" + title);
    } catch (e) {
      goalDialogError("np", goalErrorMessage(e));
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function submitHabit(event) {
    if (event) event.preventDefault();
    var submit = el("nh-submit");
    var title = (el("nh-title").value || "").trim();
    var startDate = el("nh-start").value;
    var frequency = el("nh-freq").value === "weekly" ? "weekly" : "daily";
    var weekdays = selectedHabitWeekdays();
    var time = el("nh-time").value;
    var durationRaw = (el("nh-duration").value || "").trim();
    if (!title) { goalDialogError("nh", "请填写习惯名称。"); return; }
    if (!startDate) { goalDialogError("nh", "请选择开始日期。"); return; }
    if (frequency === "weekly" && !weekdays.length) { goalDialogError("nh", "每周重复至少选择一天。"); return; }
    var durationMinutes = null;
    if (durationRaw) {
      durationMinutes = Number(durationRaw);
      if (!isFinite(durationMinutes) || Math.round(durationMinutes) !== durationMinutes || durationMinutes < 1 || durationMinutes > 600) {
        goalDialogError("nh", "时长需为 1 到 600 分钟的整数。");
        return;
      }
    }
    var payload = {
      kind: "habit",
      title: title,
      startDate: startDate,
      recurrence: {
        freq: frequency,
        weekdays: frequency === "weekly" ? weekdays : [],
        time: time || null,
        durationMinutes: durationMinutes,
      },
    };
    var description = (el("nh-description").value || "").trim();
    if (description) payload.description = description;
    var error = el("nh-error");
    if (error) error.hidden = true;
    if (submit) submit.disabled = true;
    try {
      await apiClient.createGoal(payload);
      closeGoalDialog("habit");
      await loadGoals();
      showToast("已新建习惯：" + title);
    } catch (e) {
      goalDialogError("nh", goalErrorMessage(e));
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function archiveGoal(goalId) {
    if (!goalId) return;
    var confirmed = window.confirm("归档后该长期任务不再显示在清单中，关联待办不受影响。确定归档？");
    if (!confirmed) return;
    try {
      await apiClient.archiveGoal(goalId);
      if (state.goalDetail && state.goalDetail.id === goalId) closeGoalDetail();
      await loadGoals();
      showToast("已归档该长期任务。");
    } catch (e) {
      showError(e);
    }
  }

  function bindGoals() {
    var planButton = el("btn-new-plan");
    if (planButton) planButton.addEventListener("click", function () { openGoalDialog("plan"); });
    var habitButton = el("btn-new-habit");
    if (habitButton) habitButton.addEventListener("click", function () { openGoalDialog("habit"); });
    var planCancel = el("np-cancel");
    if (planCancel) planCancel.addEventListener("click", function () { closeGoalDialog("plan"); });
    var habitCancel = el("nh-cancel");
    if (habitCancel) habitCancel.addEventListener("click", function () { closeGoalDialog("habit"); });
    var planForm = el("new-plan-form");
    if (planForm) planForm.addEventListener("submit", submitPlan);
    var habitForm = el("new-habit-form");
    if (habitForm) habitForm.addEventListener("submit", submitHabit);
    [planForm, habitForm].forEach(function (form) {
      if (!form) return;
      form.addEventListener("input", hideGoalDialogError);
      form.addEventListener("change", hideGoalDialogError);
    });
    var frequency = el("nh-freq");
    if (frequency) frequency.addEventListener("change", updateHabitWeekdays);
    var goalList = el("goal-list");
    if (goalList) {
      goalList.addEventListener("click", function (event) {
        var target = event.target && event.target.closest ? event.target.closest("[data-goal-action]") : null;
        if (!target) return;
        var action = target.getAttribute("data-goal-action");
        var goalId = target.getAttribute("data-goal-id");
        if (!goalId) return;
        if (action === "detail") openGoalDetail(goalId);
        else if (action === "archive") archiveGoal(goalId);
        else if (action === "plan") startGoalPlan(goalId);
        else if (action === "occurrences") generateGoalOccurrences(goalId, target);
      });
    }
    var closeButton = el("btn-goal-close");
    if (closeButton) closeButton.addEventListener("click", closeGoalDetail);
    var archiveButton = el("btn-goal-archive");
    if (archiveButton) {
      archiveButton.addEventListener("click", function () {
        if (state.goalDetail) archiveGoal(state.goalDetail.id);
      });
    }
    var aiButton = el("btn-goal-ai");
    if (aiButton) {
      aiButton.addEventListener("click", function () {
        if (state.goalDetail) startGoalPlan(state.goalDetail.id);
      });
    }
    var occurrencesButton = el("btn-goal-occurrences");
    if (occurrencesButton) {
      occurrencesButton.addEventListener("click", function () {
        if (state.goalDetail) generateGoalOccurrences(state.goalDetail.id, occurrencesButton);
      });
    }
    // 规划预览内的操作：移除草稿 / 保存 / 取消 / 重试
    var goalDetailContent = el("goal-detail-content");
    if (goalDetailContent) {
      goalDetailContent.addEventListener("click", function (event) {
        var actionButton = event.target && event.target.closest ? event.target.closest("[data-plan-action]") : null;
        if (!actionButton) return;
        var action = actionButton.getAttribute("data-plan-action");
        if (action === "remove") removePlanDraft(actionButton.getAttribute("data-plan-index"));
        else if (action === "save") savePlanDrafts();
        else if (action === "dismiss") dismissPlanPreview();
        else if (action === "replan") startGoalPlan(state.goalPlan.goalId);
      });
    }
    var drawer = el("goal-drawer");
    if (drawer) {
      drawer.addEventListener("click", function (event) {
        var link = event.target && event.target.closest ? event.target.closest('a[href^="#/tasks/"]') : null;
        if (link) closeGoalDetail();
      });
    }
    listen(document, "keydown", function (event) {
      if (event.key === "Escape" && state.goalDetail) closeGoalDetail();
    });
  }

  // ---------------- 手动新建待办 ----------------

  function showNewTaskError(text) {
    var error = el("nt-error");
    if (error) { error.textContent = text; error.hidden = false; }
  }

  function clearNewTaskError() {
    var error = el("nt-error");
    if (error) { error.hidden = true; error.textContent = ""; }
  }

  // 提醒三选一：不提醒 / 提前 N 分钟 / 指定提醒时间；按选择只显示对应输入。
  function updateNewTaskReminderFields() {
    var modeInput = el("nt-reminder-mode");
    var mode = modeInput ? modeInput.value : "none";
    var relativeFields = el("nt-relative-fields");
    if (relativeFields) relativeFields.hidden = mode !== "relative";
    var manualField = el("nt-manual-field");
    if (manualField) manualField.hidden = mode !== "manual";
  }

  function openNewTaskDialog() {
    var dialog = el("new-task-dialog");
    if (!dialog) return;
    closeGoalDetail();
    var form = el("new-task-form");
    if (form) form.reset();
    var today = new Date();
    var pad = function (n) { return String(n).padStart(2, "0"); };
    var dateInput = el("nt-date");
    if (dateInput) dateInput.value = today.getFullYear() + "-" + pad(today.getMonth() + 1) + "-" + pad(today.getDate());
    clearNewTaskError();
    updateNewTaskReminderFields();
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
    var title = el("nt-title");
    if (title) title.focus();
  }

  function closeNewTaskDialog() {
    var dialog = el("new-task-dialog");
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close(); else dialog.removeAttribute("open");
  }

  // 提交前的本地校验：提醒的三种方式各有前置条件，不满足时在弹窗内提示，
  // 避免把必然 422 的请求发给后端（错误信息只有笼统的「任务字段校验失败。」）。
  function validateNewTaskReminder(payload) {
    var mode = payload.reminder.mode;
    if (mode === "relative") {
      if (!(payload.dueTime && payload.dueTime.precision === "datetime")) {
        showNewTaskError("设置「提前提醒」需要填写截止日期和截止时间；不需要提醒可以改为「不提醒」。");
        if (el("nt-date") && !el("nt-date").value) el("nt-date").focus();
        else if (el("nt-time")) el("nt-time").focus();
        return false;
      }
      var offset = payload.reminder.offsetMinutes;
      if (!isFinite(offset) || Math.round(offset) !== offset || offset < 1 || offset > 10080) {
        showNewTaskError("提前分钟数需要是 1 到 10080 之间的整数。");
        if (el("nt-reminder-offset")) el("nt-reminder-offset").focus();
        return false;
      }
      return true;
    }
    if (mode === "manual") {
      if (!payload.reminder.requestedAt) {
        showNewTaskError("请填写提醒时间，或把提醒改为「不提醒」。");
        if (el("nt-reminder-at")) el("nt-reminder-at").focus();
        return false;
      }
      if (new Date(payload.reminder.requestedAt).getTime() <= Date.now()) {
        showNewTaskError("提醒时间需要晚于现在，请重新选择。");
        if (el("nt-reminder-at")) el("nt-reminder-at").focus();
        return false;
      }
      return true;
    }
    return true;
  }

  async function submitNewTask(event) {
    if (event) event.preventDefault();
    var error = el("nt-error");
    var submit = el("nt-submit");
    var payload = buildManualTaskPayload({
      title: el("nt-title").value,
      date: el("nt-date").value,
      time: el("nt-time").value,
      requirements: el("nt-requirements").value,
      reminderMode: el("nt-reminder-mode").value,
      reminderOffset: el("nt-reminder-offset").value,
      reminderAt: el("nt-reminder-at").value,
    });
    if (!payload.title) {
      showNewTaskError("请填写任务名称。");
      return;
    }
    if (!validateNewTaskReminder(payload)) return;
    if (submit) submit.disabled = true;
    clearNewTaskError();
    try {
      await apiClient.createTask(payload);
      closeNewTaskDialog();
      state.filter = "all";
      // 期6-A：新建后把月历切到该任务所在月份并取消日期筛选，避免被当前筛选隐藏。
      state.calendar.scope = "all";
      state.calendar.selectedDate = null;
      var createdDate = parseDateKey(payload.dueTime ? String(payload.dueTime.resolvedValue || "") : "");
      if (createdDate) {
        state.calendar.year = createdDate.year;
        state.calendar.month = createdDate.month;
      }
      await loadList();
      showView("list");
      navigate("#/tasks");
    } catch (e) {
      if (error) { error.textContent = (e && e.message) || "保存失败，请重试。"; error.hidden = false; }
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  function bindNewTaskDialog() {
    var openBtn = el("btn-new-task");
    if (openBtn) openBtn.addEventListener("click", openNewTaskDialog);
    var cancelBtn = el("nt-cancel");
    if (cancelBtn) cancelBtn.addEventListener("click", closeNewTaskDialog);
    var form = el("new-task-form");
    if (form) {
      form.addEventListener("submit", submitNewTask);
      // 用户一改动就清掉上一次的内联提示，避免旧错误挂着让人误会。
      form.addEventListener("input", clearNewTaskError);
      form.addEventListener("change", function () {
        clearNewTaskError();
        updateNewTaskReminderFields();
      });
    }
  }

  function bindForm() {
    var form = el("task-form");
    if (!form) return;
    state.form = {
      title: el("f-title").value,
      startTime: {
        enabled: el("f-start-enabled").checked,
        rawExpression: el("f-start-raw").value,
        precision: el("f-start-precision").value,
        resolvedValue: readDatePicker(el("f-start-resolved")),
        needsConfirmation: el("f-start-needs").checked,
      },
      dueTime: {
        enabled: el("f-due-enabled").checked,
        rawExpression: el("f-due-raw").value,
        precision: el("f-due-precision").value,
        resolvedValue: readDatePicker(el("f-due-resolved")),
        needsConfirmation: el("f-due-needs").checked,
      },
      requirementsText: el("f-requirements").value,
      applicabilityStatus: el("f-app-status").value,
      applicabilityText: el("f-app-text").value,
      sourceExcerpt: el("f-excerpt").value === "" ? null : el("f-excerpt").value,
      reminder: {
        mode: el("f-rem-mode").value,
        requestedAt: readDatePicker(el("f-rem-requested")),
        relativeTo: el("f-rem-relative-to").value,
        offsetMinutes: el("f-rem-offset").value,
      },
      status: el("f-status").value,
    };
  }

  function fillForm(task) {
    var form = formMapping.taskToForm(task);
    el("f-title").value = form.title;
    setTimeFields("f-start", form.startTime);
    setTimeFields("f-due", form.dueTime);
    el("f-requirements").value = form.requirementsText;
    el("f-app-status").value = form.applicabilityStatus;
    el("f-app-text").value = form.applicabilityText;
    el("f-excerpt").value = form.sourceExcerpt === null ? "" : form.sourceExcerpt;
    el("f-rem-mode").value = form.reminder.mode;
    fillDatePicker(el("f-rem-requested"), form.reminder.requestedAt);
    el("f-rem-relative-to").value = form.reminder.relativeTo;
    el("f-rem-offset").value = form.reminder.offsetMinutes;
    el("f-status").value = form.status;
    el("btn-toggle-status").textContent = task.status === "completed" ? "重新打开" : "标为完成";
    updateDetailReminder();
    renderReminderMeta(task.reminder);
    bindForm();
  }

  function setTimeFields(prefix, timeForm) {
    el(prefix + "-enabled").checked = timeForm.enabled;
    el(prefix + "-raw").value = timeForm.rawExpression;
    el(prefix + "-precision").value = timeForm.precision;
    el(prefix + "-resolved").type = timeForm.enabled && timeForm.precision === "date" ? "date" : "datetime-local";
    fillDatePicker(el(prefix + "-resolved"), timeForm.resolvedValue);
    el(prefix + "-needs").checked = timeForm.needsConfirmation;
  }

  function renderReminderMeta(reminder) {
    var meta = el("reminder-meta");
    if (!meta) return;
    meta.textContent = "提醒：" + reminderBadge(reminder) + (reminder.scheduledAt ? " · " + readableTime(reminder.scheduledAt) : "");
  }

  async function saveDetail() {
    if (!state.detail || state.saving) return;
    bindForm();
    state.saving = true;
    clearError();
    try {
      var body = formMapping.formToPatchBody(state.form, state.detail);
      if (!Object.keys(body).length) { state.saving = false; navigate("#/tasks"); return; }
      var result = await apiClient.patchTask(state.detail.id, body);
      state.detail = result.task;
      fillForm(result.task); // 成功后才重载表单
      navigate("#/tasks");
      await loadList();
    } catch (e) {
      showError(e); // 失败保留表单：不调用 fillForm
    }
    state.saving = false;
  }

  async function toggleStatus() {
    if (!state.detail) return;
    bindForm();
    clearError();
    try {
      var next = state.detail.status === "open" ? "completed" : "open";
      var result = await apiClient.patchTask(state.detail.id, { status: next });
      state.detail = result.task;
      fillForm(result.task);
      await loadList();
    } catch (e) {
      showError(e);
    }
  }

  function openDeleteDialog(task, trigger) {
    var target = task || state.detail;
    if (!target) return;
    state.deleteTarget = target;
    state.deleteTrigger = trigger || null;
    var name = el("delete-task-name");
    if (name) name.textContent = target.title || "未命名待办";
    var error = el("delete-task-error");
    if (error) { error.hidden = true; error.textContent = ""; }
    var confirm = el("btn-delete-dialog-confirm");
    if (confirm) { confirm.disabled = false; confirm.textContent = "删除待办"; }
    var cancel = el("btn-delete-dialog-cancel");
    if (cancel) cancel.disabled = false;
    var dialog = el("delete-task-dialog");
    if (!dialog) return;
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
    } else if (!dialog.open) {
      dialog.setAttribute("open", "");
    }
    /* 打开后把焦点放在「取消」，避免回车误删。 */
    if (cancel) cancel.focus();
  }

  function closeDeleteDialog() {
    var dialog = el("delete-task-dialog");
    if (!dialog) return;
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }

  async function deleteTaskFromDialog() {
    var target = state.deleteTarget || state.detail;
    if (!target || state.deleting) return;
    state.deleting = true;
    var confirm = el("btn-delete-dialog-confirm");
    var cancel = el("btn-delete-dialog-cancel");
    var error = el("delete-task-error");
    if (confirm) { confirm.disabled = true; confirm.textContent = "正在删除…"; }
    if (cancel) cancel.disabled = true;
    if (error) { error.hidden = true; error.textContent = ""; }
    try {
      await apiClient.deleteTask(target.id);
      state.deleteTrigger = null;
      state.deleteTarget = null;
      state.detail = null;
      closeDeleteDialog();
      showToast("已删除待办");
      navigate("#/tasks");
      await loadList();
      if (state.goals.length) loadGoals();
      /* 删除完成后把焦点放回列表主操作，键盘/读屏用户不会丢失位置。 */
      var newTaskBtn = el("btn-new-task");
      if (newTaskBtn) newTaskBtn.focus();
    } catch (e) {
      if (error) {
        error.textContent = (e && e.message) || "删除失败，请重试。";
        error.hidden = false;
      }
      if (confirm) { confirm.disabled = false; confirm.textContent = "删除待办"; }
      if (cancel) cancel.disabled = false;
    } finally {
      state.deleting = false;
    }
  }

  async function showSource() {
    if (!state.detailSource) return;
    var panel = el("source-content");
    panel.innerHTML = "";
    clearError();

    // T13：image 源回看原图（/content 原始字节 → blob URL）；410 → 原图缺失
    if (state.detailSource.kind === "image") {
      try {
        var url = await apiClient.getSourceImage(state.detailSource.id);
        var img = document.createElement("img");
        img.className = "source-image";
        img.alt = "来源截图";
        img.src = url;
        panel.appendChild(img);
      } catch (e) {
        if (e.code === "source_content_missing") {
          panel.textContent = MODEL_ERROR_TEXT.source_content_missing;
        } else {
          showError(e);
        }
      }
      return;
    }

    try {
      var text = await apiClient.getSourceContent(state.detailSource.id);
      // content 端点返回纯文本（text 源）
      var pre = document.createElement("pre");
      pre.textContent = text;
      panel.appendChild(pre);
    } catch (e) {
      showError(e);
    }
  }

  async function loadDetail(id) {
    clearError();
    try {
      var data = await apiClient.getTask(id);
      state.detail = data.task;
      state.detailSource = data.source;
      var meta = el("source-meta");
      if (meta) {
        meta.textContent =
          "来源：" + (data.source.kind === "image" ? "截图" : "粘贴文字") + " · 导入于 " + readableTime(data.source.importedAt);
      }
      fillForm(data.task);
      var sourcePanel = el("source-content");
      if (sourcePanel) sourcePanel.innerHTML = "";
      // T13：图片来源时按钮改为「查看原图」
      var sourceBtn = el("btn-show-source");
      if (sourceBtn) {
        sourceBtn.textContent = data.source.kind === "image" ? "查看原图" : "查看原文";
      }
      showView("detail");
      if (el("task-list") && !el("task-list").children.length) loadList();
    } catch (e) {
      showError(e);
      navigate("#/tasks");
    }
  }

  // ============================================================== 导入视图
  // 粘贴原文 → 提取 → 进核对视图。任何失败都保留输入（A02/A10）。
  // T13：截图导入与文字互斥——有文件走图片 multipart，无文件走文字 JSON。

  var IMAGE_NAME_PATTERN = /\.(png|jpe?g)$/i;
  var IMAGE_MIMES = ["image/png", "image/jpeg"];

  function isSupportedImage(file) {
    if (!file) return false;
    var type = (file.type || "").toLowerCase();
    if (type && IMAGE_MIMES.indexOf(type) === -1) return false;
    return IMAGE_NAME_PATTERN.test(file.name || "");
  }

  function importModeHint() {
    var hint = el("import-mode");
    if (!hint) return;
    if (state.file) {
      var sizeKb = Math.max(1, Math.round((state.file.size || 0) / 1024));
      hint.hidden = false;
      hint.textContent = "当前：截图模式（" + state.file.name + " · " + sizeKb + " KB）。点「清除截图」回到文字模式。";
      hint.className = "notice notice-info";
    } else {
      hint.hidden = true;
      hint.textContent = "";
      hint.className = "notice";
    }
    updateImportPresentation();
  }

  // 工作台 CSP 为 img-src 'self' data:，blob: URL 会被浏览器拦截；
  // 因此截图预览与来源原图都经 FileReader 转成 data: URL（纯本地，不上传）。
  function readAsDataUrl(blob) {
    return new Promise(function (resolve) {
      if (!blob || typeof FileReader === "undefined") { resolve(""); return; }
      var reader = new FileReader();
      reader.onload = function () { resolve(typeof reader.result === "string" ? reader.result : ""); };
      reader.onerror = function () { resolve(""); };
      reader.readAsDataURL(blob);
    });
  }

  function revokePreviewUrl() {
    // data: URL 无需 revoke；递增 token 让仍在读取的旧 FileReader 结果作废。
    state.filePreviewToken++;
    state.filePreviewUrl = null;
  }

  // 导入界面的可测入口（node 桥 + DOM 桩驱动，见 tests/test_frontend_image_import.py）
  var importView = {
    mode: function () {
      return formMapping.importMode(!!state.file);
    },

    // 选中截图：清空并禁用文字框（互斥防呆），本地 blob 预览
    selectFile: function (file) {
      if (!file) {
        importView.clearFile();
        return "text";
      }
      revokePreviewUrl();
      state.file = file;
      state.importTab = "image";

      var textarea = el("import-text");
      if (textarea) {
        textarea.value = "";
        textarea.disabled = true;
      }

      var preview = el("import-preview");
      if (preview) {
        preview.innerHTML = "";
        var img = document.createElement("img");
        img.className = "preview-img";
        img.alt = "截图预览";
        var previewToken = ++state.filePreviewToken;
        readAsDataUrl(file).then(function (url) {
          if (!url || previewToken !== state.filePreviewToken) return;
          state.filePreviewUrl = url;
          img.src = url;
        });
        img.addEventListener("click", function () { openImage(img.src, "截图预览"); });
        preview.appendChild(img);

        var meta = document.createElement("span");
        meta.className = "preview-meta";
        meta.textContent = (file.name || "截图") + " · " +
          Math.max(1, Math.round((file.size || 0) / 1024)) + " KB";
        preview.appendChild(meta);
        preview.hidden = false;
      }
      importModeHint();
      return "image";
    },

    // 清除截图：恢复文字模式，释放预览 URL
    clearFile: function () {
      revokePreviewUrl();
      state.file = null;
      var preview = el("import-preview");
      if (preview) {
        preview.innerHTML = "";
        preview.hidden = true;
      }
      var textarea = el("import-text");
      if (textarea) textarea.disabled = false;
      var input = el("import-file");
      if (input) input.value = "";
      importModeHint();
      return "text";
    },

    // 文字被编辑 → 退出截图模式（互斥的另一侧）
    onTextEdited: function () {
      if (state.file) importView.clearFile();
      return importView.mode();
    },

    // no_tasks：信息样式提示（输入保留，可换图或改文字）
    showNoTasksNotice: function () {
      setImportNotice("未发现待办事项。可修改原文或更换截图后重新提取。", "info");
    },

    // 失败：把 ApiError 映射成可读文案（按 code 分型）
    errorFor: function (error) {
      var text = MODEL_ERROR_TEXT[error && error.code];
      return {
        status: (error && error.status) || 0,
        code: (error && error.code) || "unknown_error",
        message: text || (error && error.message) || "提取失败。",
        fieldErrors: (error && error.fieldErrors) || [],
      };
    },
  };

  async function doExtract() {
    if (state.extracting) return;
    var textarea = el("import-text");
    var dateInput = el("import-date");
    var file = state.file;

    var messageDate = dateInput && dateInput.value ? dateInput.value : null;

    // 前端先校验 messageDate 格式（预防 400），失败也保留输入
    if (messageDate && !/^\d{4}-\d{2}-\d{2}$/.test(messageDate)) {
      showError({
        status: 400,
        code: "invalid_request",
        message: "消息日期需为 YYYY-MM-DD 格式，或留空。",
        fieldErrors: [],
      });
      return;
    }

    if (file) {
      // 截图模式：本机预检格式，避免把明显不支持的字节发给服务端
      if (!isSupportedImage(file)) {
        showError({
          status: 415,
          code: "unsupported_media_type",
          message: MODEL_ERROR_TEXT.unsupported_media_type,
          fieldErrors: [],
        });
        return;
      }
      state.extracting = true;
      updateImportPresentation();
      clearError();
      setImportNotice(null);
      try {
        var form = new FormData();
        formMapping.buildImageExtractionFields(file, messageDate).forEach(function (pair) {
          if (pair[0] === "file") form.append("file", pair[1], pair[1].name || "shot.png");
          else form.append(pair[0], pair[1]);
        });
        var imageDraftSet = await apiClient.extractImage(form);
        state.draftSet = imageDraftSet;
        state.originalText = "";
        state.drafts = (imageDraftSet.drafts || []).map(function (d) {
          return prepareCaptureDraft(d, new Date(), imageDraftSet.source.messageDate);
        });
        if (imageDraftSet.status === "no_tasks") {
          importView.showNoTasksNotice();
          return;
        }
        navigate("#/review");
      } catch (e) {
        // 失败保留已选截图与日期（A10），按 code 分型
        showError(importView.errorFor(e));
      } finally {
        state.extracting = false;
        updateImportPresentation();
      }
      return;
    }

    if (!textarea) return;
    var originalText = textarea.value;
    if (!originalText.trim()) {
      showError({
        status: 400,
        code: "invalid_request",
        message: "请先粘贴通知原文，或选择一张截图。",
        fieldErrors: [],
      });
      return;
    }

    state.extracting = true;
    updateImportPresentation();
    clearError();
    setImportNotice(null);
    try {
      var draftSet = await apiClient.extract(
        formMapping.buildExtractionPayload(originalText, messageDate)
      );
      state.draftSet = draftSet;
      state.originalText = originalText;
      state.drafts = (draftSet.drafts || []).map(function (d) {
        return prepareCaptureDraft(d, new Date(), draftSet.source.messageDate);
      });
      if (draftSet.status === "no_tasks") {
        // 信息样式，非错误（A02）
        setImportNotice("未发现待办事项。可修改原文后重新提取。", "info");
        return;
      }
      navigate("#/review");
    } catch (e) {
      // 失败：输入保留，按 code 显示可读文案（绝不伪装 no_tasks）
      showImportError(e);
    } finally {
      state.extracting = false;
      updateImportPresentation();
    }
  }

  function showImportError(error) {
    var text = MODEL_ERROR_TEXT[error.code];
    showError({
      status: error.status,
      code: error.code,
      message: text || error.message || "提取失败。",
      fieldErrors: error.fieldErrors || [],
    });
  }

  function setImportNotice(message, kind) {
    var box = el("import-notice");
    if (!box) return;
    if (!message) {
      box.hidden = true;
      box.textContent = "";
      box.className = "notice";
      return;
    }
    box.hidden = false;
    box.textContent = message;
    box.className = "notice notice-" + (kind || "info");
  }

  // ============================================================== 核对视图
  // 草稿可编辑/移除 → 确认保存。review 状态不持久化（刷新即失＝契约语义）。

  function appendPreviewImage(panel, alt) {
    if (!state.file && !state.filePreviewUrl) {
      panel.appendChild(textNode("p", "hint", "原图已不在内存，请返回导入重新选择截图。"));
      return;
    }
    var img = document.createElement("img");
    img.alt = alt;
    img.addEventListener("click", function () { openImage(img.src, alt); });
    panel.appendChild(img);
    if (state.filePreviewUrl) { img.src = state.filePreviewUrl; return; }
    var token = state.filePreviewToken;
    readAsDataUrl(state.file).then(function (url) {
      if (!url || token !== state.filePreviewToken) return;
      state.filePreviewUrl = url;
      img.src = url;
    });
  }

  function renderReviewSource() {
    var panel = el("review-original");
    if (!panel) return;
    panel.innerHTML = "";
    var source = state.draftSet && state.draftSet.source;
    if (!source) return;
    var kind = el("review-source-kind");
    if (kind) kind.textContent = source.kind === "image" ? "上传截图" : "粘贴文字";
    var meta = el("review-meta");
    if (meta) meta.textContent = (source.fileName ? source.fileName + " · " : "") + (source.messageDate ? "消息日期：" + source.messageDate : "未提供消息日期");
    if (source.kind === "image") {
      appendPreviewImage(panel, "本次导入的原始截图");
    } else {
      panel.appendChild(textNode("pre", "", state.originalText));
    }
  }

  function renderDrafts() {
    var container = el("draft-list");
    if (!container) return;
    container.innerHTML = "";
    renderReviewSource();
    if (!state.drafts.length) {
      container.appendChild(textNode("p", "empty", "没有待保存的草稿。请返回导入页重新提取。"));
      renderIssuesPreview();
      return;
    }
    state.drafts.forEach(function (draft, index) {
      var card = document.createElement("article");
      card.className = "draft-card";
      card.setAttribute("data-draft-index", String(index));
      var head = document.createElement("div");
      head.className = "draft-head";
      head.appendChild(textNode("span", "", "任务 " + (index + 1)));
      head.appendChild(textNode("span", "badge draft-state", ""));
      var remove = textNode("button", "btn btn-secondary btn-small", "移除");
      remove.type = "button";
      remove.addEventListener("click", function () { state.drafts.splice(index, 1); renderDrafts(); });
      head.appendChild(remove);
      card.appendChild(head);
      var title = fieldRow("任务标题", function () {
        var input = document.createElement("input");
        input.type = "text"; input.value = draft.title;
        input.addEventListener("input", function () { draft.title = input.value; });
        return input;
      });
      title.className = "field-title";
      card.appendChild(title);
      var times = document.createElement("div");
      times.className = "time-grid";
      times.appendChild(timeFieldRow("开始时间", draft, "startTime"));
      times.appendChild(timeFieldRow("截止时间", draft, "dueTime"));
      card.appendChild(times);
      card.appendChild(fieldRow("执行要求（每行一条）", function () {
        var area = document.createElement("textarea"); area.rows = 3;
        area.value = (draft.requirements || []).join("\n");
        area.addEventListener("input", function () {
          draft.requirements = area.value.split("\n").map(function (line) { return line.trim(); }).filter(Boolean);
        }); return area;
      }));
      var condition = document.createElement("div"); condition.className = "condition-editor";
      var statusSelect;
      condition.appendChild(fieldRow("适用条件", function () {
        var input = document.createElement("input"); input.type = "text";
        input.value = draft.applicability.text || ""; input.placeholder = "例如：仅限本班同学；没有则留空";
        input.addEventListener("input", function () {
          draft.applicability.text = input.value.trim() || null;
          if (!draft.applicability.text) draft.applicability.status = "not_stated";
          else if (draft.applicability.status === "not_stated") draft.applicability.status = "needs_confirmation";
          statusSelect.value = draft.applicability.status;
          renderIssuesPreview();
        }); return input;
      }));
      condition.appendChild(fieldRow("条件核对", function () {
        statusSelect = document.createElement("select");
        [["not_stated","原文未限定"],["confirmed","已确认适用于我"],["needs_confirmation","还需要确认"]].forEach(function (option) {
          var node = textNode("option", "", option[1]); node.value = option[0]; statusSelect.appendChild(node);
        });
        statusSelect.value = draft.applicability.status;
        statusSelect.addEventListener("change", function () { draft.applicability.status = statusSelect.value; renderIssuesPreview(); });
        return statusSelect;
      }));
      card.appendChild(condition);
      var excerpt = document.createElement("details");
      excerpt.className = "excerpt-editor";
      excerpt.appendChild(textNode("summary", "", "对应原文"));
      excerpt.appendChild(fieldRow("原文片段", function () {
        var area = document.createElement("textarea"); area.rows = 2; area.value = draft.sourceExcerpt || "";
        area.addEventListener("input", function () { draft.sourceExcerpt = area.value.trim() || null; renderIssuesPreview(); });
        return area;
      }));
      excerpt.open = true;
      card.appendChild(excerpt);
      card.appendChild(reminderFieldRow(draft));
      card.appendChild(textNode("ul", "issue-list", ""));
      container.appendChild(card);
    });
    renderIssuesPreview();
  }

  function fieldRow(labelText, buildInput) {
    var label = document.createElement("label");
    label.textContent = labelText;
    var control = buildInput();
    control.setAttribute("aria-label", labelText);
    label.appendChild(control);
    return label;
  }

  function timeFieldRow(labelText, draft, key) {
    var form = formMapping.timeInfoToForm(draft[key]);
    var wrap = document.createElement("fieldset");
    wrap.className = "time-editor" + (form.needsConfirmation ? " is-unresolved" : "");
    wrap.appendChild(textNode("legend", "", labelText));
    var enable = document.createElement("label"); enable.className = "inline";
    var check = document.createElement("input"); check.type = "checkbox"; check.checked = form.enabled;
    enable.appendChild(check); enable.appendChild(document.createTextNode("设置" + labelText)); wrap.appendChild(enable);
    var picker = document.createElement("input");
    picker.type = form.enabled && form.precision === "date" ? "date" : "datetime-local"; picker.step = "any";
    picker.setAttribute("aria-label", labelText);
    fillDatePicker(picker, form.resolvedValue);
    wrap.appendChild(picker);
    var rawHint = textNode("p", "hint", key === "startTime" && draft._defaultStart ? "默认今天：" + form.resolvedValue + "，可修改。" : (form.rawExpression ? "原文：" + form.rawExpression : "原文未给出，可留空。"));
    wrap.appendChild(rawHint);
    var advanced = document.createElement("details");
    advanced.appendChild(textNode("summary", "", "原文与时间核对"));
    var rawInput;
    advanced.appendChild(fieldRow("原始表达", function () {
      rawInput = document.createElement("input"); rawInput.type = "text"; rawInput.value = form.rawExpression;
      rawInput.addEventListener("input", function () { form.rawExpression = rawInput.value; apply(); }); return rawInput;
    }));
    var precisionSelect;
    advanced.appendChild(fieldRow("时间精度", function () {
      precisionSelect = document.createElement("select");
      [["datetime","日期和时间"],["date","仅日期"],["day_part","上午 / 下午等时段"],["relative","相对日期"],["unknown","尚不明确"]].forEach(function (option) {
        var node = textNode("option", "", option[1]); node.value = option[0]; precisionSelect.appendChild(node);
      });
      precisionSelect.value = form.precision;
      precisionSelect.addEventListener("change", function () {
        var previous = readDatePicker(picker);
        form.precision = precisionSelect.value;
        picker.type = form.precision === "date" ? "date" : "datetime-local";
        form.resolvedValue = form.precision === "date" ? previous.slice(0, 10) : (previous.indexOf("T") >= 0 ? previous : "");
        fillDatePicker(picker, form.resolvedValue);
        form.needsConfirmation = !form.resolvedValue || ["date", "datetime"].indexOf(form.precision) < 0;
        needsCheck.checked = form.needsConfirmation; apply();
      }); return precisionSelect;
    }));
    var needs = document.createElement("label"); needs.className = "inline";
    var needsCheck = document.createElement("input"); needsCheck.type = "checkbox"; needsCheck.checked = form.needsConfirmation;
    needs.appendChild(needsCheck); needs.appendChild(document.createTextNode("时间仍待核对")); advanced.appendChild(needs);
    wrap.appendChild(advanced);
    picker.addEventListener("input", function () {
      form.enabled = true; check.checked = true;
      form.precision = picker.type === "date" ? "date" : "datetime"; precisionSelect.value = form.precision;
      form.resolvedValue = readDatePicker(picker);
      form.needsConfirmation = !picker.value; needsCheck.checked = form.needsConfirmation;
      if (!form.rawExpression) { form.rawExpression = readableTime(form.resolvedValue); rawInput.value = form.rawExpression; }
      apply();
    });
    check.addEventListener("change", function () {
      form.enabled = check.checked;
      if (form.enabled && !form.resolvedValue) { form.needsConfirmation = true; needsCheck.checked = true; }
      apply();
    });
    needsCheck.addEventListener("change", function () { form.needsConfirmation = needsCheck.checked; apply(); });
    function apply() {
      if (key === "startTime") draft._defaultStart = false;
      draft._automaticReminderFrozen = false;
      draft[key] = formMapping.timeInfoFromForm(form);
      refreshAutomaticReminder(draft);
      if (draft._refreshReminderView) draft._refreshReminderView();
      wrap.className = "time-editor" + (form.enabled && form.needsConfirmation ? " is-unresolved" : "");
      rawHint.textContent = form.rawExpression ? "原文：" + form.rawExpression : "原文未给出，可留空。";
      renderIssuesPreview();
    }
    wrap._apply = apply;
    return wrap;
  }

  function reminderFieldRow(draft) {
    var form = formMapping.reminderToForm(draft.reminder);
    var wrap = document.createElement("fieldset"); wrap.className = "reminder-editor";
    wrap.appendChild(textNode("legend", "", "提醒设置"));
    var automaticNote = textNode("p", "hint automatic-reminder", draft._automaticReminder ? draft._reminderDefaultText : "");
    automaticNote.hidden = !draft._automaticReminder;
    wrap.appendChild(automaticNote);
    var modeSelect;
    wrap.appendChild(fieldRow("提醒方式", function () {
      modeSelect = document.createElement("select");
      [["none","不提醒"],["manual","指定时间"],["relative","提前提醒"]].forEach(function (option) {
        var node = textNode("option", "", option[1]); node.value = option[0]; modeSelect.appendChild(node);
      }); modeSelect.value = form.mode; return modeSelect;
    }));
    var manual = fieldRow("提醒时间", function () {
      var input = document.createElement("input"); input.type = "datetime-local"; input.step = "any"; fillDatePicker(input, form.requestedAt);
      input.addEventListener("input", function () { form.requestedAt = readDatePicker(input); apply(); }); return input;
    });
    wrap.appendChild(manual);
    var relative = document.createElement("div"); relative.className = "two-fields";
    relative.appendChild(fieldRow("相对时间", function () {
      var select = document.createElement("select");
      [["","请选择"],["start","开始时间"],["due","截止时间"]].forEach(function (option) { var node = textNode("option", "", option[1]); node.value = option[0]; select.appendChild(node); });
      select.value = form.relativeTo;
      select.addEventListener("change", function () { form.relativeTo = select.value; apply(); }); return select;
    }));
    relative.appendChild(fieldRow("提前分钟数", function () {
      var input = document.createElement("input"); input.type = "number"; input.min = "1"; input.value = form.offsetMinutes;
      input.addEventListener("input", function () { form.offsetMinutes = input.value; apply(); }); return input;
    }));
    wrap.appendChild(relative);
    wrap.appendChild(textNode("p", "hint", "时间或适用条件未确认时，不会启用相关提醒。"));
    function showFields() { manual.hidden = form.mode !== "manual"; relative.hidden = form.mode !== "relative"; }
    modeSelect.addEventListener("change", function () { form.mode = modeSelect.value; showFields(); apply(); });
    showFields();
    function apply() {
      draft._automaticReminder = false;
      automaticNote.hidden = true;
      var mapped = formMapping.reminderFromForm(form);
      draft.reminder = {
        mode: mapped.mode, requestedAt: mapped.requestedAt, relativeTo: mapped.relativeTo, offsetMinutes: mapped.offsetMinutes,
        scheduledAt: null, state: "not_set", acknowledgedAt: null, revision: null
      };
      renderIssuesPreview();
    }
    draft._refreshReminderView = function () {
      if (!draft._automaticReminder) return;
      form = formMapping.reminderToForm(draft.reminder);
      modeSelect.value = form.mode;
      fillDatePicker(manual.querySelector("input"), form.requestedAt);
      relative.querySelector("select").value = form.relativeTo;
      relative.querySelector("input").value = form.offsetMinutes;
      automaticNote.textContent = draft._reminderDefaultText;
      showFields();
    };
    wrap._apply = apply;
    return wrap;
  }

  function renderIssuesPreview() {
    var pending = 0;
    scope.querySelectorAll("[data-draft-index]").forEach(function (card) {
      var draft = state.drafts[Number(card.getAttribute("data-draft-index"))];
      if (!draft) return;
      var messages = pendingMessages(draft);
      if (messages.length) pending++;
      var badge = card.querySelector(".draft-state");
      badge.className = "badge draft-state" + (messages.length ? " needs-review" : " is-completed");
      badge.textContent = messages.length ? "待补充" : "可直接保存";
      var issues = card.querySelector(".issue-list"); issues.innerHTML = ""; issues.hidden = !messages.length;
      messages.forEach(function (message) { issues.appendChild(textNode("li", "", message)); });
    });
    var count = el("review-count"); if (count) count.textContent = state.drafts.length + " 条任务";
    var summary = el("review-summary"); if (summary) summary.textContent = (state.drafts.length - pending) + " 条可直接保存，" + pending + " 条待补充";
    var save = el("btn-confirm-drafts");
    if (save) { save.disabled = state.confirming || !state.drafts.length; save.textContent = state.confirming ? "正在保存…" : "保存全部待办（" + state.drafts.length + "）"; }
    scope.querySelectorAll("#draft-list input, #draft-list textarea, #draft-list select, #draft-list button").forEach(function (control) { control.disabled = state.confirming; });
    var back = el("btn-back-import"); if (back) back.disabled = state.confirming;
  }

  async function doConfirm(retrySnapshot) {
    var attempt = retrySnapshot && retrySnapshot.payload ? retrySnapshot : null;
    if ((!state.draftSet && !attempt) || state.confirming) return;
    // 空确认：不发请求（报告说明选择）
    if (!attempt && !state.drafts.length) {
      showError({
        status: 422,
        code: "empty_confirmation",
        message: "请至少保留一条待办再保存。",
        fieldErrors: [],
      });
      return;
    }

    var isImage = attempt ? attempt.isImage : state.draftSet.source && state.draftSet.source.kind === "image";
    // T13 坑①：图片确认必须重传原图——File 不在内存时明确要求重新选图，不发残缺请求
    if (isImage && !(attempt ? attempt.file : state.file)) {
      showError({
        status: 400,
        code: "invalid_request",
        message: "原图已不在内存，请返回导入页重新选择截图后再保存。",
        fieldErrors: [],
      });
      return;
    }

    state.confirming = true;
    if (!attempt) state.drafts.forEach(function (draft) {
      refreshAutomaticReminder(draft);
      if (draft._automaticReminder) draft._automaticReminderFrozen = true;
      if (draft._refreshReminderView) draft._refreshReminderView();
    });
    renderIssuesPreview();
    clearError();
    // T13 坑②：时间对象只回传四键（normalizeTimeInfo 已剔除服务端 timeZone）
    if (!attempt) {
      var payload = isImage
        ? formMapping.buildImageConfirmationPayload(state.draftSet, state.drafts)
        : formMapping.buildConfirmationPayload(state.draftSet, state.originalText, state.drafts);
      attempt = {draftSetId:state.draftSet.draftSetId, isImage:isImage, file:state.file, payload:JSON.parse(JSON.stringify(payload))};
    }
    state.confirmationAttempt = attempt;
    try {
      var result = isImage
        ? await apiClient.confirmImage(attempt.draftSetId, attempt.file, attempt.payload)
        : await apiClient.confirmDraftSet(attempt.draftSetId, attempt.payload);
      state.confirmationAttempt = null;
      state.draftSet = null;
      state.drafts = [];
      state.originalText = "";
      if (isImage) importView.clearFile();
      setImportNotice("已保存 " + (result.tasks || []).length + " 条待办。", "ok");
      navigate("#/tasks");
      await loadList();
    } catch (e) {
      // 网络错误/超时：结果未知，不伪装成功（A06）
      if (e.status === 0) {
        showUnknownOutcome();
      } else {
        showError(e);
      }
      // 编辑与输入全保留，可原样重试
    } finally {
      state.confirming = false;
      renderIssuesPreview();
    }
  }

  function showUnknownOutcome() {
    var panel = el("error-panel");
    if (!panel) return;
    panel.innerHTML = "";
    panel.hidden = false;
    var title = document.createElement("strong");
    title.textContent = "结果未知，可重试同请求或去列表查看。";
    panel.appendChild(title);

    var retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "重试同一请求";
    var snapshot = state.confirmationAttempt;
    retry.addEventListener("click", function () { doConfirm(snapshot); });
    panel.appendChild(retry);

    var goList = document.createElement("button");
    goList.type = "button";
    goList.textContent = "去列表看看";
    goList.addEventListener("click", function () {
      navigate("#/tasks");
    });
    panel.appendChild(goList);
  }

  // ---------------- 提醒弹层 DOM（仅浏览器执行）----------------

  var reminderState = {
    poller: null,
    sessionId: null,
    timer: null,
    stopped: false,   // 卸载后置 true：阻止轮询/异步回调继续动 DOM
    shown: {},        // 会话内已展示（内存）；同时写 sessionStorage 跨刷新保持会话语义
    pending: [],      // 队列：逐条弹出
  };

  function reminderStore() {
    // sessionStorage 可注入封装；不可用时退化为内存对象
    try {
      if (typeof sessionStorage !== "undefined" && sessionStorage) {
        return {
          get: function (k) { return sessionStorage.getItem("s2t:" + k); },
          set: function (k, v) { sessionStorage.setItem("s2t:" + k, v); },
        };
      }
    } catch (e) { /* 隐私模式等 → 退化为内存 */ }
    var mem = {};
    return {
      get: function (k) { return Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null; },
      set: function (k, v) { mem[k] = v; },
    };
  }

  function renderReminderItem(item) {
    // 队列方案：一次只渲染一条（报告说明选择）
    var layer = el("reminder-layer");
    if (!layer) return;
    var list = el("reminder-items");
    list.innerHTML = "";

    var card = document.createElement("div");
    card.className = "reminder-card";

    var title = document.createElement("strong");
    title.textContent = item.title || "（无标题）";
    card.appendChild(title);

    var when = document.createElement("span");
    when.className = "reminder-when";
    when.textContent = "提醒时间：" + (readableTime(item.scheduledAt) || "未知");
    card.appendChild(when);

    var src = document.createElement("span");
    src.className = "reminder-source";
    src.textContent = "请及时查看任务和执行要求。";
    card.appendChild(src);

    var actions = document.createElement("div");
    actions.className = "reminder-actions";

    var ack = document.createElement("button");
    ack.type = "button";
    ack.className = "btn btn-primary btn-small";
    ack.textContent = "确认";
    ack.addEventListener("click", function () { submitAck(item); });
    actions.appendChild(ack);

    var later = document.createElement("button");
    later.type = "button";
    later.className = "btn btn-secondary btn-small";
    later.textContent = "稍后";
    later.addEventListener("click", function () {
      // 「稍后」仅写去重键，不调用任何接口
      reminderLayer.markShown(reminderStore(), item);
      closeReminderCard();
    });
    actions.appendChild(later);

    var unknown = document.createElement("p");
    unknown.className = "reminder-unknown";
    unknown.hidden = true;
    card.appendChild(actions);
    card.appendChild(unknown);
    card._unknown = unknown;
    list.appendChild(card);
    layer.hidden = false;
  }

  function closeReminderCard() {
    var list = el("reminder-items");
    if (list) list.innerHTML = "";
    var layer = el("reminder-layer");
    if (layer && !reminderState.pending.length) layer.hidden = true;
  }

  function showUnknown(message) {
    var list = el("reminder-items");
    if (!list) return;
    var box = list.firstChild;
    if (box && box._unknown) {
      box._unknown.hidden = false;
      box._unknown.textContent = message;
    }
  }

  async function submitAck(item) {
    if (!reminderState.sessionId) return;
    try {
      await apiClient.acknowledgeReminder({
        taskId: item.taskId,
        sessionId: reminderState.sessionId,
        reminderVersion: item.reminderVersion,
      });
      // 200 才标记已确认并关层
      reminderLayer.markShown(reminderStore(), item);
      closeReminderCard();
    } catch (e) {
      var mapped = reminderLayer.mapAckResult({
        status: e.status,
        code: e.code,
        message: e.message,
      });
      if (mapped.action === "refresh") {
        // 409 not_acknowledgeable：刷新该任务状态后关层
        try {
          await apiClient.getTask(item.taskId);
        } catch (ignore) { /* 刷新失败也不伪装成功 */ }
        reminderLayer.markShown(reminderStore(), item);
        closeReminderCard();
        return;
      }
      // 结果未知：提示 + 重试/去任务看看
      showUnknown("结果未知：可重试确认，或去任务详情查看当前状态。");
      var list = el("reminder-items");
      if (list) {
        var retry = document.createElement("button");
        retry.type = "button";
        retry.className = "btn btn-secondary btn-small";
        retry.textContent = "重试确认";
        retry.addEventListener("click", function () { submitAck(item); });
        list.appendChild(retry);

        var go = document.createElement("a");
        go.className = "btn btn-secondary btn-small";
        go.textContent = "去任务看看";
        go.href = "#/tasks/" + item.taskId;
        list.appendChild(go);
      }
    }
  }

  function openReminderLayer(items) {
    var store = reminderStore();
    reminderState.pending = (items || []).filter(function (item) {
      return reminderLayer.shouldShow(store, item);
    });
    if (!reminderState.pending.length) return;
    var next = reminderState.pending.shift();
    reminderLayer.markShown(store, next);
    renderReminderItem(next);
  }

  function startReminderPoller() {
    if (reminderState.poller) return;
    var poller = reminderLayer.createReminderPoller({
      api: {
        openSession: async function () {
          var s = await apiClient.openReminderSession();
          reminderState.sessionId = s.sessionId;
          return s;
        },
        due: async function () {
          return apiClient.dueReminders(reminderState.sessionId);
        },
      },
      visibility: {
        isHidden: function () {
          return typeof document !== "undefined" && document.hidden;
        },
      },
      onDue: openReminderLayer,
      onSessionLost: function () {
        reminderState.sessionId = null;
      },
    });
    reminderState.poller = poller;

    poller.start().then(function () {
      if (reminderState.stopped) return;
      var schedule = function () {
        if (reminderState.timer) clearInterval(reminderState.timer);
        reminderState.timer = setInterval(function () {
          poller.tick().catch(function () { /* 单次失败不中断节奏 */ });
        }, poller.intervalSeconds() * 1000);
      };
      schedule();
      // 可见性恢复 → 立即查一次并恢复节奏
      listen(document, "visibilitychange", function () {
        if (!document.hidden) {
          poller.tick().catch(function () {});
          schedule();
        }
      });
    });
  }

  function showView(name) {
    var openListBtn = el("btn-open-list");
    if (openListBtn) openListBtn.hidden = name === "list";
    var map = {
      list: "view-list",
      detail: "view-detail",
      import: "view-import",
      review: "view-review",
    };
    Object.keys(map).forEach(function (key) {
      var node = el(map[key]);
      if (node) node.hidden = key !== name && !(name === "detail" && key === "list");
    });
    scope.querySelectorAll("[data-nav]").forEach(function (link) {
      var active = link.getAttribute("data-nav") === ((name === "list" || name === "detail") ? "list" : "import");
      link.className = "nav-link" + (active ? " is-active" : "");
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    });
    [["step-import", name === "import"], ["step-review", name === "review"], ["step-save", name === "list" || name === "detail"]].forEach(function (item) { var step = el(item[0]); if (step) step.className = item[1] ? "is-active" : ""; });
    // document.title 由工作台外壳统一维护，模块不接管。
    if (name === "import") updateImportPresentation();
  }

  // 工作台外壳用 location.hash 做路由（#/tasks 等）；模块内部视图路由只维护
  // 内存状态并直接渲染，不写 location.hash（否则外壳会重新挂载或渲染 404）。
  var currentRoute = "#/import";

  function navigate(hash) {
    if (hash === currentRoute) return;
    // 离开核对视图且有未保存草稿 → 原生确认（对应源实现的 hashchange 监听）
    if (state.draftSet && state.drafts.length && hash !== "#/review") {
      var leave = window.confirm("有尚未保存的草稿，离开将丢失。确定离开？");
      if (!leave) return;
    }
    currentRoute = hash;
    onRoute();
  }

  function onRoute() {
    var hash = currentRoute;
    // 期6-B：目标详情是列表页内的临时抽屉，切换内部路由时一律收起。
    if (state.goalDetail) closeGoalDetail();
    if (hash.indexOf("#/tasks/") === 0) {
      var id = hash.slice("#/tasks/".length);
      showView("detail");
      loadDetail(id);
      return;
    }
    if (hash === "#/import") {
      showView("import");
      return;
    }
    if (hash === "#/review") {
      showView("review");
      renderDrafts();
      return;
    }
    showView("list");
    loadList();
    loadGoals();
  }

  function handleImportPaste(event) {
    // 仅导入视图接收图片粘贴；文字粘贴走默认行为（textarea 等）
    if (el("view-import").hidden || state.extracting || !event.clipboardData) return;
    var items = event.clipboardData.items || [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].type && items[i].type.indexOf("image/") === 0) {
        var blob = items[i].getAsFile();
        if (!blob) return;
        event.preventDefault();
        if (!isSupportedImage(blob)) {
          showError({ status: 415, code: "unsupported_media_type", message: MODEL_ERROR_TEXT.unsupported_media_type, fieldErrors: [] });
          return;
        }
        if (!blob.name) {
          try { blob = new File([blob], "pasted-" + shanghaiTimestamp(new Date()).replace(/[:+]/g, "-") + (blob.type === "image/jpeg" ? ".jpg" : ".png"), { type: blob.type }); }
          catch (e) { /* 旧浏览器 File 构造不支持时保留原名 */ }
        }
        importView.selectFile(blob);
        updateImportPresentation();
        setImportNotice("已粘贴剪贴板截图，可提取待办。", "ok");
        return;
      }
    }
  }

  // B（辅）：按钮兜底读取剪贴板；不可用时引导用 Ctrl+V
  async function pasteFromClipboard() {
    if (state.extracting) return;
    if (!(navigator.clipboard && navigator.clipboard.read)) {
      showError({ message: "当前浏览器不支持按钮粘贴，请在导入页直接按 Ctrl+V 粘贴截图。" });
      return;
    }
    try {
      var items = await navigator.clipboard.read();
      for (var i = 0; i < items.length; i++) {
        var type = items[i].types && items[i].types.find ? items[i].types.find(function (t) { return t.indexOf("image/") === 0; }) : null;
        if (!type) continue;
        var blob = await items[i].getType(type);
        if (!isSupportedImage(blob)) {
          showError({ status: 415, code: "unsupported_media_type", message: MODEL_ERROR_TEXT.unsupported_media_type, fieldErrors: [] });
          return;
        }
        if (!blob.name) {
          blob = new File([blob], "pasted-" + shanghaiTimestamp(new Date()).replace(/[:+]/g, "-") + (type === "image/jpeg" ? ".jpg" : ".png"), { type: type });
        }
        importView.selectFile(blob);
        updateImportPresentation();
        setImportNotice("已粘贴剪贴板截图，可提取待办。", "ok");
        return;
      }
      showError({ message: "剪贴板里没有图片。截图后回到本页再按 Ctrl+V，或点此按钮粘贴。" });
    } catch (e) {
      showError({ message: "未能读取剪贴板（" + ((e && e.name) || "未知错误") + "）。可改在导入页直接按 Ctrl+V 粘贴截图。" });
    }
  }

function bindGlobal() {
    if (!el("import-date").value) el("import-date").value = shanghaiTimestamp(new Date()).slice(0,10);
    var skip = scope.querySelector(".skip-link");
    if (skip) skip.addEventListener("click", function (event) {
      event.preventDefault(); app.setAttribute("tabindex", "-1"); app.focus();
    });
    el("tab-shot").addEventListener("click", function () { switchImportTab("image"); });
    el("tab-text").addEventListener("click", function () { switchImportTab("text"); });
    ["tab-shot", "tab-text"].forEach(function (id) {
      el(id).addEventListener("keydown", function (event) {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          switchImportTab(id === "tab-shot" ? "text" : "image");
          el(id === "tab-shot" ? "tab-text" : "tab-shot").focus();
        }
      });
    });
    el("task-search").addEventListener("input", function () { state.search = el("task-search").value; renderList(); });
    el("btn-change-file").addEventListener("click", function () { el("import-file").click(); });
    listen(document, "paste", handleImportPaste);
    var pasteBtn = el("btn-paste-image");
    if (pasteBtn) pasteBtn.addEventListener("click", pasteFromClipboard);
    var dropzone = el("dropzone");
    ["dragenter", "dragover"].forEach(function (type) { dropzone.addEventListener(type, function (event) { event.preventDefault(); dropzone.className = "dropzone is-dragging"; }); });
    ["dragleave", "drop"].forEach(function (type) { dropzone.addEventListener(type, function (event) {
      event.preventDefault(); dropzone.className = "dropzone";
      if (type !== "drop" || state.extracting) return;
      var files = event.dataTransfer && event.dataTransfer.files;
      if (!files || !files.length) return;
      if (files.length !== 1 || !isSupportedImage(files[0])) { showError({message:"请一次选择一张 PNG 或 JPEG 截图。"}); return; }
      importView.selectFile(files[0]);
    }); });
    ["f-start", "f-due"].forEach(function (prefix) {
      var picker = el(prefix + "-resolved");
      picker.addEventListener("input", function () {
        el(prefix + "-enabled").checked = true;
        el(prefix + "-needs").checked = !picker.value;
        el(prefix + "-precision").value = picker.type === "date" ? "date" : "datetime";
        if (!el(prefix + "-raw").value) el(prefix + "-raw").value = readableTime(toApiTime(picker.value));
      });
      el(prefix + "-enabled").addEventListener("change", function () { if (this.checked && !picker.value) el(prefix + "-needs").checked = true; });
      el(prefix + "-precision").addEventListener("change", function () {
        var previous = picker.value;
        picker.type = this.value === "date" ? "date" : "datetime-local";
        picker.value = this.value === "date" ? previous.slice(0, 10) : (previous.indexOf("T") >= 0 ? previous : "");
        el(prefix + "-needs").checked = !picker.value || ["date","datetime"].indexOf(this.value) < 0;
      });
    });
    el("f-rem-mode").addEventListener("change", updateDetailReminder);
    el("f-app-text").addEventListener("input", function () {
      var condition = el("f-app-status");
      if (!this.value.trim()) condition.value = "not_stated";
      else if (condition.value === "not_stated") condition.value = "needs_confirmation";
    });
    // 列表筛选
    scope.querySelectorAll("[data-filter]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.filter = btn.getAttribute("data-filter");
        loadList();
      });
    });
    // 期6-A：清单页月历（切月 / 回到今天 / 点日期筛选 / 全部与未安排切换）
    var calendarGrid = el("cal-grid");
    if (calendarGrid) {
      calendarGrid.addEventListener("click", function (event) {
        var cell = event.target && event.target.closest ? event.target.closest("[data-cal-date]") : null;
        if (!cell) return;
        selectCalendarDate(cell.getAttribute("data-cal-date"));
      });
    }
    var calendarPrev = el("cal-prev");
    if (calendarPrev) calendarPrev.addEventListener("click", function () { shiftCalendarMonth(-1); });
    var calendarNext = el("cal-next");
    if (calendarNext) calendarNext.addEventListener("click", function () { shiftCalendarMonth(1); });
    var calendarToday = el("cal-today");
    if (calendarToday) calendarToday.addEventListener("click", goCalendarToday);
    scope.querySelectorAll("[data-cal-scope]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setCalendarScope(btn.getAttribute("data-cal-scope"));
      });
    });
    var saveBtn = el("btn-save");
    if (saveBtn) saveBtn.addEventListener("click", saveDetail);
    var toggleBtn = el("btn-toggle-status");
    if (toggleBtn) toggleBtn.addEventListener("click", toggleStatus);
    var deleteBtn = el("btn-delete");
    if (deleteBtn) {
      deleteBtn.addEventListener("click", function (event) {
        openDeleteDialog(state.detail, event.currentTarget);
      });
    }
    var deleteTopBtn = el("btn-delete-top");
    if (deleteTopBtn) {
      deleteTopBtn.addEventListener("click", function (event) {
        openDeleteDialog(state.detail, event.currentTarget);
      });
    }
    var deleteDialog = el("delete-task-dialog");
    if (deleteDialog) {
      deleteDialog.addEventListener("cancel", function (event) {
        event.preventDefault();
        if (!state.deleting) closeDeleteDialog();
      });
      deleteDialog.addEventListener("click", function (event) {
        if (state.deleting || event.target !== deleteDialog) return;
        /* 只有点在弹窗外（遮罩）才关闭；点在弹窗自身 padding 上不关闭。 */
        var rect = deleteDialog.getBoundingClientRect();
        var inside = event.clientX >= rect.left && event.clientX <= rect.right
          && event.clientY >= rect.top && event.clientY <= rect.bottom;
        if (!inside) closeDeleteDialog();
      });
      deleteDialog.addEventListener("close", function () {
        if (state.deleteTrigger && state.deleteTrigger.isConnected) state.deleteTrigger.focus();
        state.deleteTrigger = null;
        state.deleteTarget = null;
      });
    }
    var deleteConfirmBtn = el("btn-delete-dialog-confirm");
    if (deleteConfirmBtn) deleteConfirmBtn.addEventListener("click", deleteTaskFromDialog);
    var deleteCancelBtn = el("btn-delete-dialog-cancel");
    if (deleteCancelBtn) {
      deleteCancelBtn.addEventListener("click", function () {
        if (!state.deleting) closeDeleteDialog();
      });
    }
    var backBtn = el("btn-back");
    if (backBtn) backBtn.addEventListener("click", function () { navigate("#/tasks"); });
    var sourceBtn = el("btn-show-source");
    if (sourceBtn) sourceBtn.addEventListener("click", showSource);
    var reloadBtn = el("btn-reload");
    if (reloadBtn) {
      reloadBtn.addEventListener("click", function () {
        loadList();
        loadGoals();
      });
    }
    // 工作台外壳没有源侧栏，导入视图补一个进入已有待办列表的入口（源侧栏「我的待办」）
    var openListBtn = el("btn-open-list");
    if (openListBtn) openListBtn.addEventListener("click", function () { navigate("#/tasks"); });

    bindNewTaskDialog();
    // 期6-B：长期任务区（新建计划/习惯、卡片操作、详情抽屉、归档、AI 占位）
    bindGoals();

    // T09：导入与核对
    var extractBtn = el("btn-extract");
    if (extractBtn) extractBtn.addEventListener("click", doExtract);

    // T13：截图导入（选图/清除/文字输入互斥）
    var fileInput = el("import-file");
    if (fileInput) {
      fileInput.addEventListener("change", function () {
        var file = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
        if (file) importView.selectFile(file);
        else importView.onTextEdited();
      });
    }
    var clearFileBtn = el("btn-clear-file");
    if (clearFileBtn) {
      clearFileBtn.addEventListener("click", function () { importView.clearFile(); updateImportPresentation(); });
    }
    var importTextArea = el("import-text");
    if (importTextArea) {
      importTextArea.addEventListener("input", function () { importView.onTextEdited(); updateImportPresentation(); });
    }

    var confirmBtn = el("btn-confirm-drafts");
    if (confirmBtn) confirmBtn.addEventListener("click", doConfirm);
    var backImportBtn = el("btn-back-import");
    if (backImportBtn) {
      backImportBtn.addEventListener("click", function () {
        navigate("#/import");
      });
    }

    // 离站确认已并入 navigate()，不再监听 hashchange（工作台外壳占用 location.hash）。
    // 模块内所有 href="#/..." 链接统一拦截，改走内部 navigate()，否则会触发
    // 外壳路由把 #/tasks/{id} 当成未知页面重新挂载。
    listen(scope, "click", function (event) {
      var link = event.target && event.target.closest ? event.target.closest('a[href^="#/"]') : null;
      if (!link) return;
      event.preventDefault();
      navigate(link.getAttribute("href"));
    });
    // 源模板用 onsubmit="return false"（CSP 内联事件违规）；这里用监听替代
    ["import-form", "task-form"].forEach(function (id) {
      var form = el(id);
      if (form) form.addEventListener("submit", function (event) { event.preventDefault(); });
    });
  }

  // ============================================================== 生命周期
  // 源实现是页面级 IIFE，加载即绑定全部 window/document 监听；嵌入工作台后由
  // 外壳按路由挂载/卸载，因此改为实例级 destroy()：解绑监听、停轮询、清弹层。
  function destroy() {
    if (reminderState.stopped) return;
    reminderState.stopped = true;
    if (state.toastTimer) { clearTimeout(state.toastTimer); state.toastTimer = null; }
    if (reminderState.timer) { clearInterval(reminderState.timer); reminderState.timer = null; }
    try { if (reminderState.poller) reminderState.poller.stop(); } catch (e) { /* 忽略 */ }
    while (disposers.length) {
      try { (disposers.pop())(); } catch (e) { /* 忽略 */ }
    }
    revokePreviewUrl();
    scope.querySelectorAll("dialog").forEach(function (dialog) {
      try { if (dialog.open) dialog.close(); } catch (e) { /* 忽略 */ }
      dialog.remove();
    });
  }

  // 初始化：绑定交互 → 默认进入导入视图 → 开启提醒轮询（仅页面打开期间）
  // deps.reminders === false 时由工作台外壳统一轮询，模块内不再重复开
  bindGlobal();
  onRoute();
  if (deps.reminders !== false) startReminderPoller();

  return { destroy: destroy, navigate: navigate, state: state };
}
