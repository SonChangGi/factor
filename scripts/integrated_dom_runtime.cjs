const jsdom = require('jsdom');
const QuantFormat = require('./fixtures/quant-number.js');
// Production startup prepares this shared formatter before deferred page scripts.
class JSDOM extends jsdom.JSDOM {
  constructor(html, options = {}) {
    const beforeParse = options.beforeParse;
    super(html, { ...options, beforeParse(window) {
      window.QuantFormat = QuantFormat;
      if (beforeParse) beforeParse(window);
    } });
  }
}
module.exports = { ...jsdom, JSDOM };
