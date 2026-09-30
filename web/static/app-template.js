window.LemonAdminRender = (function (Vue) {
const { createCommentVNode: _createCommentVNode, createElementVNode: _createElementVNode, vModelText: _vModelText, withDirectives: _withDirectives, createTextVNode: _createTextVNode, toDisplayString: _toDisplayString, renderList: _renderList, Fragment: _Fragment, openBlock: _openBlock, createElementBlock: _createElementBlock } = Vue

return function render(_ctx, _cache) {
  return (_openBlock(), _createElementBlock(_Fragment, null, [
    _createCommentVNode(" Navbar "),
    _createElementVNode("header", { class: "bg-slate-900 border-b border-slate-800 px-6 py-4 flex items-center justify-between shadow-lg" }, [
      _createElementVNode("div", { class: "flex items-center space-x-3" }, [
        _createElementVNode("span", { class: "text-3xl" }, "🍋"),
        _createElementVNode("div", null, [
          _createElementVNode("h1", { class: "text-xl font-bold bg-gradient-to-r from-amber-400 to-orange-500 bg-clip-text text-transparent" }, "Lemon Emby Control Panel"),
          _createElementVNode("p", { class: "text-xs text-slate-400" }, "Emby 用户管理与 Telegram 智能运营中控")
        ])
      ]),
      _createElementVNode("div", { class: "flex items-center space-x-4" }, [
        _withDirectives(_createElementVNode("input", {
          "onUpdate:modelValue": $event => ((_ctx.token) = $event),
          type: "password",
          placeholder: "Admin Secret Token",
          class: "bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-amber-500"
        }, null, 8 /* PROPS */, ["onUpdate:modelValue"]), [
          [_vModelText, _ctx.token]
        ]),
        _createElementVNode("button", {
          onClick: _ctx.fetchData,
          class: "bg-amber-500 hover:bg-amber-600 text-slate-950 font-semibold px-4 py-1.5 rounded-lg text-sm transition-all flex items-center space-x-1 shadow-md shadow-amber-500/20"
        }, [
          _createElementVNode("i", { class: "fa-solid fa-rotate mr-1" }),
          _createTextVNode(" 刷新 ")
        ], 8 /* PROPS */, ["onClick"])
      ])
    ]),
    _createCommentVNode(" Main Content "),
    _createElementVNode("main", { class: "flex-1 max-w-7xl w-full mx-auto p-6 space-y-6" }, [
      _createCommentVNode(" Status Cards "),
      _createElementVNode("div", { class: "grid grid-cols-1 md:grid-cols-3 gap-6" }, [
        _createElementVNode("div", { class: "bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm" }, [
          _createElementVNode("div", { class: "flex items-center justify-between" }, [
            _createElementVNode("span", { class: "text-slate-400 text-sm font-medium" }, "总注册用户"),
            _createElementVNode("span", { class: "p-2 bg-amber-500/10 text-amber-400 rounded-lg" }, [
              _createElementVNode("i", { class: "fa-solid fa-users text-lg" })
            ])
          ]),
          _createElementVNode("div", { class: "mt-4 text-3xl font-extrabold text-white" }, _toDisplayString(_ctx.stats.total_users || 0), 1 /* TEXT */),
          _createElementVNode("div", { class: "mt-1 text-xs text-slate-500" }, "包含正常与冻结账号")
        ]),
        _createElementVNode("div", { class: "bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm" }, [
          _createElementVNode("div", { class: "flex items-center justify-between" }, [
            _createElementVNode("span", { class: "text-slate-400 text-sm font-medium" }, "当前活跃播放"),
            _createElementVNode("span", { class: "p-2 bg-emerald-500/10 text-emerald-400 rounded-lg" }, [
              _createElementVNode("i", { class: "fa-solid fa-play text-lg" })
            ])
          ]),
          _createElementVNode("div", { class: "mt-4 text-3xl font-extrabold text-white" }, _toDisplayString(_ctx.stats.active_sessions || 0), 1 /* TEXT */),
          _createElementVNode("div", { class: "mt-1 text-xs text-emerald-400" }, "实时媒体并发流")
        ]),
        _createElementVNode("div", { class: "bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm" }, [
          _createElementVNode("div", { class: "flex items-center justify-between" }, [
            _createElementVNode("span", { class: "text-slate-400 text-sm font-medium" }, "Emby 服务器状态"),
            _createElementVNode("span", { class: "p-2 bg-blue-500/10 text-blue-400 rounded-lg" }, [
              _createElementVNode("i", { class: "fa-solid fa-server text-lg" })
            ])
          ]),
          _createElementVNode("div", { class: "mt-4 text-xl font-bold text-white" }, _toDisplayString(_ctx.stats.server_info?.ServerName || '正在连接...'), 1 /* TEXT */),
          _createElementVNode("div", { class: "mt-1 text-xs text-slate-400" }, "版本: " + _toDisplayString(_ctx.stats.server_info?.Version || 'N/A'), 1 /* TEXT */)
        ])
      ]),
      _createCommentVNode(" Live Sessions "),
      _createElementVNode("div", { class: "bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-sm" }, [
        _createElementVNode("h2", { class: "text-lg font-bold text-white mb-4 flex items-center" }, [
          _createElementVNode("i", { class: "fa-solid fa-circle-play text-amber-400 mr-2" }),
          _createTextVNode(" 实时在线播放会话（实时风控监控） ")
        ]),
        (_ctx.stats.sessions && _ctx.stats.sessions.length > 0)
          ? (_openBlock(), _createElementBlock("div", {
              key: 0,
              class: "overflow-x-auto"
            }, [
              _createElementVNode("table", { class: "w-full text-left text-sm text-slate-300" }, [
                _createElementVNode("thead", { class: "text-xs uppercase bg-slate-800/60 text-slate-400" }, [
                  _createElementVNode("tr", null, [
                    _createElementVNode("th", { class: "px-4 py-3 rounded-l-lg" }, "用户"),
                    _createElementVNode("th", { class: "px-4 py-3" }, "客户端 / 设备"),
                    _createElementVNode("th", { class: "px-4 py-3" }, "当前播放媒体"),
                    _createElementVNode("th", { class: "px-4 py-3" }, "IP / 节点"),
                    _createElementVNode("th", { class: "px-4 py-3 rounded-r-lg text-right" }, "操作")
                  ])
                ]),
                _createElementVNode("tbody", { class: "divide-y divide-slate-800" }, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(_ctx.stats.sessions, (s) => {
                    return (_openBlock(), _createElementBlock("tr", {
                      key: s.Id,
                      class: "hover:bg-slate-800/30"
                    }, [
                      _createElementVNode("td", { class: "px-4 py-3 font-semibold text-white" }, _toDisplayString(s.UserName), 1 /* TEXT */),
                      _createElementVNode("td", { class: "px-4 py-3 text-slate-400" }, [
                        _createTextVNode(_toDisplayString(s.DeviceName) + " ", 1 /* TEXT */),
                        _createElementVNode("span", { class: "text-xs text-amber-500/80" }, "(" + _toDisplayString(s.Client) + ")", 1 /* TEXT */)
                      ]),
                      _createElementVNode("td", { class: "px-4 py-3 text-amber-300 font-medium" }, _toDisplayString(s.NowPlayingItem?.Name || '未知'), 1 /* TEXT */),
                      _createElementVNode("td", { class: "px-4 py-3 text-slate-400 font-mono text-xs" }, _toDisplayString(s.RemoteEndPoint || '内网'), 1 /* TEXT */),
                      _createElementVNode("td", { class: "px-4 py-3 text-right" }, [
                        _createElementVNode("button", {
                          onClick: $event => (_ctx.killSession(s.Id)),
                          class: "bg-rose-500/20 hover:bg-rose-500/40 text-rose-400 px-3 py-1 rounded-md text-xs font-semibold transition"
                        }, " 踢下线 ", 8 /* PROPS */, ["onClick"])
                      ])
                    ]))
                  }), 128 /* KEYED_FRAGMENT */))
                ])
              ])
            ]))
          : (_openBlock(), _createElementBlock("div", {
              key: 1,
              class: "text-center py-8 text-slate-500 text-sm"
            }, " 暂无在线播放会话 "))
      ]),
      _createCommentVNode(" Card Key Generator & Users "),
      _createElementVNode("div", { class: "grid grid-cols-1 lg:grid-cols-3 gap-6" }, [
        _createCommentVNode(" Generator "),
        _createElementVNode("div", { class: "bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-sm" }, [
          _createElementVNode("h2", { class: "text-lg font-bold text-white mb-4 flex items-center" }, [
            _createElementVNode("i", { class: "fa-solid fa-ticket text-amber-400 mr-2" }),
            _createTextVNode(" 快速生成卡密 ")
          ]),
          _createElementVNode("div", { class: "space-y-4" }, [
            _createElementVNode("div", null, [
              _createElementVNode("label", { class: "block text-xs text-slate-400 mb-1" }, "有效时长（天）"),
              _withDirectives(_createElementVNode("input", {
                "onUpdate:modelValue": $event => ((_ctx.genForm.value) = $event),
                type: "number",
                class: "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              }, null, 8 /* PROPS */, ["onUpdate:modelValue"]), [
                [
                  _vModelText,
                  _ctx.genForm.value,
                  void 0,
                  { number: true }
                ]
              ])
            ]),
            _createElementVNode("div", null, [
              _createElementVNode("label", { class: "block text-xs text-slate-400 mb-1" }, "生成数量"),
              _withDirectives(_createElementVNode("input", {
                "onUpdate:modelValue": $event => ((_ctx.genForm.count) = $event),
                type: "number",
                class: "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              }, null, 8 /* PROPS */, ["onUpdate:modelValue"]), [
                [
                  _vModelText,
                  _ctx.genForm.count,
                  void 0,
                  { number: true }
                ]
              ])
            ]),
            _createElementVNode("button", {
              onClick: _ctx.generateCodes,
              class: "w-full bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-slate-950 font-bold py-2 rounded-lg text-sm transition"
            }, " 一键生成兑换码 ", 8 /* PROPS */, ["onClick"]),
            (_ctx.generatedCodes.length > 0)
              ? (_openBlock(), _createElementBlock("div", {
                  key: 0,
                  class: "mt-4 p-3 bg-slate-950 rounded-lg border border-slate-800 font-mono text-xs text-amber-400 max-h-40 overflow-y-auto space-y-1"
                }, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(_ctx.generatedCodes, (c) => {
                    return (_openBlock(), _createElementBlock("div", { key: c }, _toDisplayString(c), 1 /* TEXT */))
                  }), 128 /* KEYED_FRAGMENT */))
                ]))
              : _createCommentVNode("v-if", true)
          ])
        ]),
        _createCommentVNode(" Users Table "),
        _createElementVNode("div", { class: "lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-sm" }, [
          _createElementVNode("h2", { class: "text-lg font-bold text-white mb-4 flex items-center" }, [
            _createElementVNode("i", { class: "fa-solid fa-id-card text-amber-400 mr-2" }),
            _createTextVNode(" 注册用户列表 ")
          ]),
          _createElementVNode("div", { class: "overflow-x-auto max-h-80 overflow-y-auto" }, [
            _createElementVNode("table", { class: "w-full text-left text-sm text-slate-300" }, [
              _createElementVNode("thead", { class: "text-xs uppercase bg-slate-800/60 text-slate-400 sticky top-0" }, [
                _createElementVNode("tr", null, [
                  _createElementVNode("th", { class: "px-4 py-3" }, "用户名"),
                  _createElementVNode("th", { class: "px-4 py-3" }, "Telegram ID"),
                  _createElementVNode("th", { class: "px-4 py-3" }, "到期时间"),
                  _createElementVNode("th", { class: "px-4 py-3" }, "设备数"),
                  _createElementVNode("th", { class: "px-4 py-3" }, "状态")
                ])
              ]),
              _createElementVNode("tbody", { class: "divide-y divide-slate-800" }, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(_ctx.users, (u) => {
                  return (_openBlock(), _createElementBlock("tr", {
                    key: u.tg_id,
                    class: "hover:bg-slate-800/30"
                  }, [
                    _createElementVNode("td", { class: "px-4 py-3 font-semibold text-white" }, _toDisplayString(u.emby_username), 1 /* TEXT */),
                    _createElementVNode("td", { class: "px-4 py-3 font-mono text-xs text-slate-400" }, _toDisplayString(u.tg_id), 1 /* TEXT */),
                    _createElementVNode("td", { class: "px-4 py-3 text-xs" }, _toDisplayString(u.expiry_date?.slice(0, 16).replace('T', ' ')), 1 /* TEXT */),
                    _createElementVNode("td", { class: "px-4 py-3 text-xs" }, _toDisplayString(u.max_devices) + " 台", 1 /* TEXT */),
                    _createElementVNode("td", { class: "px-4 py-3" }, [
                      (u.is_disabled)
                        ? (_openBlock(), _createElementBlock("span", {
                            key: 0,
                            class: "px-2 py-0.5 rounded text-xs bg-rose-500/20 text-rose-400"
                          }, "已冻结"))
                        : (_openBlock(), _createElementBlock("span", {
                            key: 1,
                            class: "px-2 py-0.5 rounded text-xs bg-emerald-500/20 text-emerald-400"
                          }, "正常"))
                    ])
                  ]))
                }), 128 /* KEYED_FRAGMENT */))
              ])
            ])
          ])
        ])
      ])
    ])
  ], 64 /* STABLE_FRAGMENT */))
}
})(Vue);
