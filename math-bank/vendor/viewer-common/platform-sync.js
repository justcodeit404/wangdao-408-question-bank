/**
 * Platform sync helpers — cookie auth preferred, Bearer fallback.
 * Used by bank-math and bank-408 when opened under /banks/* on :8000 / :8100 (v2).
 *
 * 方向：
 * - syncFromBank：原图库 → 平台
 * - pullMasteryFromPlatform：平台 → 原图库（熟练度）
 */
(function (global) {
  'use strict';

  function onPlatformHost() {
    try {
      var p = location.pathname || '';
      if (p.indexOf('/banks/') === 0) return true;
      if (String(location.port) === '8000' || String(location.port) === '8100') return true;
      if (location.host === '127.0.0.1:8000' || location.host === 'localhost:8000') return true;
      if (location.host === '127.0.0.1:8100' || location.host === 'localhost:8100') return true;
    } catch (_) {}
    return false;
  }

  /**
   * Ensure we can call /api/* — rely on httpOnly cookie first.
   * Returns { ok, token? } where token is optional Bearer for older servers.
   */
  async function ensureAuth(opts) {
    opts = opts || {};
    // Already have cookie session?
    try {
      var me = await fetch('/api/auth/me', { credentials: 'include' });
      if (me.ok) return { ok: true, token: null };
    } catch (_) {}

    // Legacy localStorage token
    var token = null;
    try {
      token = localStorage.getItem('token');
    } catch (_) {}
    if (token) {
      try {
        var me2 = await fetch('/api/auth/me', {
          credentials: 'include',
          headers: { Authorization: 'Bearer ' + token },
        });
        if (me2.ok) return { ok: true, token: token };
      } catch (_) {}
    }

    return { ok: false, token: null };
  }

  function authHeaders(auth) {
    var headers = { 'Content-Type': 'application/json' };
    if (auth && auth.token) headers.Authorization = 'Bearer ' + auth.token;
    return headers;
  }

  async function syncFromBank(bank, items, auth) {
    auth = auth || (await ensureAuth());
    if (!auth.ok) {
      return { ok: false, error: '未登录：请先在平台登录，再从 /banks/ 打开本题库' };
    }
    try {
      var r = await fetch('/api/study-records/sync-from-bank', {
        method: 'POST',
        credentials: 'include',
        headers: authHeaders(auth),
        body: JSON.stringify({ bank: bank, items: items }),
      });
      if (!r.ok) {
        var detail = 'HTTP ' + r.status;
        try {
          var body = await r.json();
          if (body && body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
        } catch (_) {}
        return { ok: false, error: detail };
      }
      var result = await r.json();
      return { ok: true, data: result };
    } catch (e) {
      return { ok: false, error: (e && e.message) || '网络错误' };
    }
  }

  /**
   * 从平台拉取熟练度标记（反向同步）。
   * @param {string} bank - 1000 / 880 / 660 / 大学深埋 / cs408-ds / 408 …
   * @param {object} [opts]
   * @param {string} [opts.scheme] - math | 408
   * @param {object} [opts.auth]
   * @returns {{ ok:boolean, data?: { bank, scheme, items:[{uid,mark,question_id}], total }, error?: string }}
   */
  async function pullMasteryFromPlatform(bank, opts) {
    opts = opts || {};
    var auth = opts.auth || (await ensureAuth());
    if (!auth.ok) {
      return { ok: false, error: '未登录：请先在平台登录，再从 /banks/ 打开本题库' };
    }
    if (!bank) {
      return { ok: false, error: '缺少 bank 参数' };
    }
    try {
      var qs = 'bank=' + encodeURIComponent(bank);
      if (opts.scheme) qs += '&scheme=' + encodeURIComponent(opts.scheme);
      var r = await fetch('/api/study-records/bank-mastery?' + qs, {
        method: 'GET',
        credentials: 'include',
        headers: authHeaders(auth),
      });
      if (!r.ok) {
        var detail = 'HTTP ' + r.status;
        try {
          var body = await r.json();
          if (body && body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
        } catch (_) {}
        return { ok: false, error: detail };
      }
      var data = await r.json();
      return { ok: true, data: data };
    } catch (e) {
      return { ok: false, error: (e && e.message) || '网络错误' };
    }
  }

  /**
   * 合并策略：
   * - fill：仅补本地未标记
   * - overwrite：平台覆盖本地
   * - prefer_weaker：取更弱一档（不熟/不会优先），利于复习
   *
   * rank 越大越弱：mastered < fuzzy/familiar < forgot/unknown
   */
  function markRank(mark) {
    var m = String(mark || '');
    if (m === 'mastered') return 1;
    if (m === 'fuzzy' || m === 'familiar') return 2;
    if (m === 'forgot' || m === 'unknown') return 3;
    return 0;
  }

  /**
   * @param {Record<string,string>} localMap uid -> mark
   * @param {Array<{uid:string,mark:string}>} remoteItems
   * @param {'fill'|'overwrite'|'prefer_weaker'} mode
   * @returns {{ applied: number, skipped: number, map: Record<string,string> }}
   */
  function mergeMasteryMarks(localMap, remoteItems, mode) {
    mode = mode || 'prefer_weaker';
    var map = Object.assign({}, localMap || {});
    var applied = 0;
    var skipped = 0;
    (remoteItems || []).forEach(function (it) {
      if (!it || !it.uid || !it.mark) return;
      var uid = String(it.uid);
      var remote = String(it.mark);
      var local = map[uid] || '';
      var localEmpty = !local || local === 'none';

      if (mode === 'overwrite') {
        if (local === remote) {
          skipped++;
          return;
        }
        map[uid] = remote;
        applied++;
        return;
      }
      if (mode === 'fill') {
        if (!localEmpty) {
          skipped++;
          return;
        }
        map[uid] = remote;
        applied++;
        return;
      }
      // prefer_weaker
      if (localEmpty) {
        map[uid] = remote;
        applied++;
        return;
      }
      if (markRank(remote) > markRank(local)) {
        map[uid] = remote;
        applied++;
        return;
      }
      skipped++;
    });
    return { applied: applied, skipped: skipped, map: map };
  }

  global.ViewerPlatformSync = {
    onPlatformHost: onPlatformHost,
    ensureAuth: ensureAuth,
    syncFromBank: syncFromBank,
    pullMasteryFromPlatform: pullMasteryFromPlatform,
    mergeMasteryMarks: mergeMasteryMarks,
    markRank: markRank,
  };
})(typeof window !== 'undefined' ? window : globalThis);
