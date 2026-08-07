/**
 * Shared localStorage helpers for bank-math / bank-408 viewers.
 * - safeSetItem with QuotaExceeded hint
 * - sharded map storage (split large mark maps across keys)
 */
(function (global) {
  'use strict';

  var SHARD_COUNT = 8;

  function safeSetItem(key, value) {
    try {
      localStorage.setItem(key, value);
      return true;
    } catch (e) {
      var name = e && (e.name || e.code);
      if (name === 'QuotaExceededError' || name === 22 || name === 'NS_ERROR_DOM_QUOTA_REACHED') {
        console.warn('[viewer-common] localStorage full for', key);
        try {
          global.dispatchEvent(
            new CustomEvent('viewer-storage-full', { detail: { key: key } })
          );
        } catch (_) {}
        if (typeof global.alert === 'function') {
          global.alert('本地存储空间不足，请导出进度后清理浏览器数据，或减少笔记/日志。');
        }
      }
      return false;
    }
  }

  function getJSON(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      if (!raw) return fallback;
      return JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }

  function setJSON(key, obj) {
    try {
      return safeSetItem(key, JSON.stringify(obj));
    } catch (e) {
      return false;
    }
  }

  function hashUid(uid) {
    var s = String(uid || '');
    var h = 0;
    for (var i = 0; i < s.length; i++) {
      h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    }
    return Math.abs(h) % SHARD_COUNT;
  }

  /**
   * Load a map that may be stored as single key (legacy) or sharded:
   *   baseKey              → legacy full object
   *   baseKey + '__meta'   → { v: 2, shards: N }
   *   baseKey + '__s' + i  → partial object
   */
  function loadShardedMap(baseKey) {
    var meta = getJSON(baseKey + '__meta', null);
    if (meta && meta.v === 2) {
      var n = meta.shards || SHARD_COUNT;
      var out = {};
      for (var i = 0; i < n; i++) {
        var part = getJSON(baseKey + '__s' + i, {});
        if (part && typeof part === 'object') {
          for (var k in part) {
            if (Object.prototype.hasOwnProperty.call(part, k)) out[k] = part[k];
          }
        }
      }
      return out;
    }
    var legacy = getJSON(baseKey, null);
    if (legacy && typeof legacy === 'object') return legacy;
    return {};
  }

  function saveShardedMap(baseKey, map) {
    map = map || {};
    var keys = Object.keys(map);
    // small maps: keep single key for simplicity
    if (keys.length < 80) {
      // write first, then clean up old shards — keep them if the write failed
      var wrote = setJSON(baseKey, map);
      if (wrote) {
        try {
          localStorage.removeItem(baseKey + '__meta');
          for (var i = 0; i < SHARD_COUNT; i++) {
            localStorage.removeItem(baseKey + '__s' + i);
          }
        } catch (_) {}
      }
      return wrote;
    }
    var shards = [];
    for (var s = 0; s < SHARD_COUNT; s++) shards.push({});
    for (var j = 0; j < keys.length; j++) {
      var uid = keys[j];
      shards[hashUid(uid)][uid] = map[uid];
    }
    var ok = setJSON(baseKey + '__meta', { v: 2, shards: SHARD_COUNT });
    for (var t = 0; t < SHARD_COUNT; t++) {
      ok = setJSON(baseKey + '__s' + t, shards[t]) && ok;
    }
    // drop legacy blob to free space — only when shards were written ok
    if (ok) {
      try {
        localStorage.removeItem(baseKey);
      } catch (_) {}
    }
    return ok;
  }

  function clearShardedMap(baseKey) {
    try {
      localStorage.removeItem(baseKey);
      localStorage.removeItem(baseKey + '__meta');
      for (var i = 0; i < SHARD_COUNT; i++) {
        localStorage.removeItem(baseKey + '__s' + i);
      }
    } catch (_) {}
  }

  global.ViewerStorage = {
    SHARD_COUNT: SHARD_COUNT,
    safeSetItem: safeSetItem,
    getJSON: getJSON,
    setJSON: setJSON,
    loadShardedMap: loadShardedMap,
    saveShardedMap: saveShardedMap,
    clearShardedMap: clearShardedMap,
  };
})(typeof window !== 'undefined' ? window : globalThis);
