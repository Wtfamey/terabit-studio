"""Gold exemplar components for TerabitStudio v3 training data.

Each exemplar is a hand-authored, production-quality React+Tailwind component
with design-system TOKENS (@@NAME@@) that the data generator substitutes from
design_system.THEMES. One exemplar x 9 domain themes teaches the 7B the skill
that matters: FOLLOW THE DESIGN BLOCK (the v2 data hardcoded dark indigo
glassmorphism, so the model painted every domain dark-indigo -- the #1 quality
complaint). Every exemplar avoids the model's known 7B failure modes: no
multi-root JSX ternaries, no {x.icon} children, no icon-as-function, no
self-shadowing names, always `export default function`, always closed fences.
"""

HERO = """import { ArrowRight, Star, Clock, MapPin } from 'lucide-react';

const STATS = [
  { icon: Star, value: '4.9', label: 'Guest rating' },
  { icon: Clock, value: '12pm - 11pm', label: 'Open daily' },
  { icon: MapPin, value: 'Old Town', label: 'Find us' },
];

export default function Hero() {
  return (
    <section id="top" className="relative overflow-hidden">
      <div className="absolute inset-0">
        <img
          src="https://picsum.photos/seed/@@SLUG@@/1600/900"
          alt=""
          className="w-full h-full object-cover"
        />
        <div className={`absolute inset-0 bg-gradient-to-b @@GRAD@@ opacity-80`} />
      </div>

      <div className="relative max-w-6xl mx-auto px-6 pt-32 pb-24 text-center">
        <p className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full @@ACCENT_BG@@ @@ACCENT_TEXT@@ text-xs font-semibold tracking-wide uppercase">
          Welcome to @@NAME@@
        </p>
        <h1 className="font-display mt-6 text-5xl md:text-7xl font-black tracking-tight @@HEAD@@ leading-[1.05]">
          Crafted with passion,<br />served with pride
        </h1>
        <p className={`mt-6 text-lg md:text-xl @@BODY@@ max-w-2xl mx-auto`}>
          @@NAME@@ brings you an experience shaped by seasons, tradition and a
          love for honest work. Every detail is deliberate -- every visit, memorable.
        </p>
        <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
          <a
            href="#reservations"
            className={`w-full sm:w-auto px-8 py-4 @@PRIMARY@@ @@PRIMARY_HOVER@@ @@ON_PRIMARY@@ font-bold @@RADIUS@@ transition-all shadow-xl hover:-translate-y-0.5`}
          >
            Book your visit <ArrowRight className="inline w-5 h-5 ml-1" />
          </a>
          <a
            href="#menu"
            className={`w-full sm:w-auto px-8 py-4 @@SURFACE@@ @@BORDER@@ border @@HEAD@@ font-bold @@RADIUS@@ hover:border-current transition-colors`}
          >
            Explore the menu
          </a>
        </div>

        <div className={`mt-16 grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-3xl mx-auto`}>
          {STATS.map((s, i) => (
            <div
              key={i}
              className={`reveal flex items-center gap-3 px-5 py-4 @@SURFACE@@ @@BORDER@@ border @@RADIUS@@ shadow-md animate-fade-up`}
              style={{ animationDelay: `${i * 120}ms` }}
            >
              <span className={`w-10 h-10 @@ACCENT_BG@@ @@ACCENT_TEXT@@ @@RADIUS@@ flex items-center justify-center`}>
                <s.icon className="w-5 h-5" />
              </span>
              <span className="text-left">
                <span className={`block font-display font-bold @@HEAD@@`}>{s.value}</span>
                <span className={`block text-xs @@MUTED@@`}>{s.label}</span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
"""

MENU = """import { useMemo, useState } from 'react';
import { Flame, Leaf, Search, Star } from 'lucide-react';

const MENU = [
  { name: 'Signature Creation', desc: 'House specialty prepared with seasonal ingredients and care', price: 18, tag: 'signature', spicy: false, veg: true },
  { name: 'Classic Favorite', desc: 'The timeless choice our guests return for every week', price: 14, tag: 'classic', spicy: false, veg: true },
  { name: 'Spicy Special', desc: 'Bold flavors with a slow kick, finished with fresh herbs', price: 16, tag: 'chef pick', spicy: true, veg: false },
  { name: 'Garden Selection', desc: 'Market-fresh vegetables, olive oil, aged cheese', price: 15, tag: 'vegetarian', spicy: false, veg: true },
  { name: "Chef's Tasting", desc: 'Five courses chosen daily by the kitchen', price: 42, tag: 'chef pick', spicy: false, veg: false },
  { name: 'Seasonal Plate', desc: 'Whatever is best this week, simply prepared', price: 19, tag: 'signature', spicy: true, veg: false },
];

export default function Menu() {
  const [query, setQuery] = useState('');
  const [onlyVeg, setOnlyVeg] = useState(false);

  const items = useMemo(
    () =>
      MENU.filter((m) =>
        m.name.toLowerCase().includes(query.toLowerCase())
      ).filter((m) => (onlyVeg ? m.veg : true)),
    [query, onlyVeg]
  );

  return (
    <section id="menu" className="py-24">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center max-w-2xl mx-auto">
          <p className={`text-sm font-bold uppercase tracking-widest @@ACCENT_TEXT@@`}>The menu</p>
          <h2 className="font-display mt-3 text-4xl md:text-5xl font-black tracking-tight @@HEAD@@">
            Made fresh, every day
          </h2>
          <p className={`mt-4 text-lg @@BODY@@`}>
            A short menu, done properly. Ingredients change with the seasons.
          </p>
        </div>

        <div className="mt-10 flex flex-col sm:flex-row items-center justify-between gap-4">
          <label className={`relative w-full sm:max-w-xs`}>
            <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 @@MUTED@@`} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search the menu..."
              className={`w-full pl-10 pr-4 py-3 @@SURFACE@@ @@BORDER@@ border @@RADIUS@@ @@HEAD@@ placeholder:@@MUTED@@ focus:outline-none focus:ring-2 focus:ring-current/30`}
            />
          </label>
          <button
            onClick={() => setOnlyVeg(!onlyVeg)}
            className={`px-5 py-3 @@RADIUS@@ border font-medium transition-colors ${
              onlyVeg
                ? `@@PRIMARY@@ @@ON_PRIMARY@@ border-transparent`
                : `@@SURFACE@@ @@BORDER@@ @@BODY@@ hover:border-current`
            }`}
          >
            <Leaf className="inline w-4 h-4 mr-2" />
            Vegetarian only
          </button>
        </div>

        <div className="mt-10 grid md:grid-cols-2 gap-6">
          {items.map((item, i) => (
            <article
              key={item.name}
              className={`reveal group @@SURFACE@@ @@BORDER@@ border @@RADIUS@@ p-6 shadow-sm hover:shadow-xl transition-all duration-300 hover:-translate-y-1 animate-fade-up`}
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="font-display text-xl font-bold @@HEAD@@ group-hover:@@ACCENT_TEXT@@ transition-colors">
                    {item.name}
                  </h3>
                  <p className={`mt-2 @@BODY@@ leading-relaxed`}>{item.desc}</p>
                  <div className="mt-4 flex items-center gap-3 text-xs">
                    <span className={`px-2.5 py-1 @@ACCENT_BG@@ @@ACCENT_TEXT@@ rounded-full font-semibold capitalize`}>
                      {item.tag}
                    </span>
                    {item.spicy && (
                      <span className="flex items-center gap-1 text-red-500 font-medium">
                        <Flame className="w-3.5 h-3.5" /> Spicy
                      </span>
                    )}
                    {item.veg && (
                      <span className="flex items-center gap-1 text-emerald-600 font-medium">
                        <Leaf className="w-3.5 h-3.5" /> Veg
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <span className="font-display text-2xl font-black @@HEAD@@">${item.price}</span>
                  <div className="mt-1 flex gap-0.5 justify-end">
                    {[...Array(5)].map((_, s) => (
                      <Star key={s} className="w-3 h-3 fill-amber-400 text-amber-400" />
                    ))}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>

        {items.length === 0 && (
          <p className={`mt-12 text-center @@MUTED@@`}>Nothing matches that search -- try another dish.</p>
        )}
      </div>
    </section>
  );
}
"""

RESERVATIONS = """import { useState } from 'react';
import { CalendarDays, CheckCircle2, Clock, Users } from 'lucide-react';

const TIMES = ['5:30 pm', '6:30 pm', '7:30 pm', '8:30 pm', '9:30 pm'];

export default function Reservations() {
  const [time, setTime] = useState(TIMES[1]);
  const [guests, setGuests] = useState(2);
  const [done, setDone] = useState(false);

  return (
    <section id="reservations" className="py-24 @@SURFACE2@@">
      <div className="max-w-4xl mx-auto px-6">
        <div className="text-center max-w-2xl mx-auto">
          <p className={`text-sm font-bold uppercase tracking-widest @@ACCENT_TEXT@@`}>Reservations</p>
          <h2 className="font-display mt-3 text-4xl md:text-5xl font-black tracking-tight @@HEAD@@">
            Reserve your table
          </h2>
          <p className={`mt-4 text-lg @@BODY@@`}>
            We hold tables for 15 minutes past the booking time.
          </p>
        </div>

        <div className={`reveal mt-12 @@SURFACE@@ @@BORDER@@ border @@RADIUS@@ shadow-xl overflow-hidden`}>
          {done ? (
            <div className="p-12 text-center">
              <CheckCircle2 className="w-14 h-14 mx-auto text-emerald-500" />
              <h3 className="font-display mt-6 text-2xl font-bold @@HEAD@@">Table reserved</h3>
              <p className={`mt-3 @@BODY@@`}>
                {guests} guests · {time} · A confirmation email is on its way.
              </p>
              <button
                onClick={() => setDone(false)}
                className={`mt-8 px-6 py-3 @@PRIMARY@@ @@PRIMARY_HOVER@@ @@ON_PRIMARY@@ font-semibold @@RADIUS@@ transition-colors`}
              >
                Book another
              </button>
            </div>
          ) : (
            <form
              className="p-8 md:p-10 grid md:grid-cols-2 gap-6"
              onSubmit={(e) => {
                e.preventDefault();
                setDone(true);
              }}
            >
              <label className="block">
                <span className={`text-sm font-semibold @@HEAD@@`}>Full name</span>
                <input
                  required
                  placeholder="Jane Doe"
                  className={`mt-2 w-full px-4 py-3 @@SURFACE2@@ @@BORDER@@ border @@RADIUS@@ @@HEAD@@ placeholder:@@MUTED@@ focus:outline-none focus:ring-2 focus:ring-current/30`}
                />
              </label>
              <label className="block">
                <span className={`text-sm font-semibold @@HEAD@@`}>Email</span>
                <input
                  required
                  type="email"
                  placeholder="jane@example.com"
                  className={`mt-2 w-full px-4 py-3 @@SURFACE2@@ @@BORDER@@ border @@RADIUS@@ @@HEAD@@ placeholder:@@MUTED@@ focus:outline-none focus:ring-2 focus:ring-current/30`}
                />
              </label>

              <div>
                <span className={`text-sm font-semibold @@HEAD@@ flex items-center gap-2`}>
                  <Users className="w-4 h-4 @@ACCENT_TEXT@@" /> Guests
                </span>
                <div className="mt-2 flex gap-2">
                  {[1, 2, 3, 4, 6, 8].map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setGuests(n)}
                      className={`w-11 h-11 @@RADIUS@@ border font-semibold transition-colors ${
                        guests === n
                          ? `@@PRIMARY@@ @@ON_PRIMARY@@ border-transparent`
                          : `@@SURFACE@@ @@BORDER@@ @@BODY@@ hover:border-current`
                      }`}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <span className={`text-sm font-semibold @@HEAD@@ flex items-center gap-2`}>
                  <Clock className="w-4 h-4 @@ACCENT_TEXT@@" /> Time
                </span>
                <div className="mt-2 flex flex-wrap gap-2">
                  {TIMES.map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setTime(t)}
                      className={`px-4 h-11 @@RADIUS@@ border text-sm font-medium transition-colors ${
                        time === t
                          ? `@@PRIMARY@@ @@ON_PRIMARY@@ border-transparent`
                          : `@@SURFACE@@ @@BORDER@@ @@BODY@@ hover:border-current`
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              <label className="block md:col-span-2">
                <span className={`text-sm font-semibold @@HEAD@@ flex items-center gap-2`}>
                  <CalendarDays className="w-4 h-4 @@ACCENT_TEXT@@" /> Special requests
                </span>
                <textarea
                  rows={3}
                  placeholder="Allergies, occasions, seating preferences..."
                  className={`mt-2 w-full px-4 py-3 @@SURFACE2@@ @@BORDER@@ border @@RADIUS@@ @@HEAD@@ placeholder:@@MUTED@@ focus:outline-none focus:ring-2 focus:ring-current/30`}
                />
              </label>

              <button
                type="submit"
                className={`md:col-span-2 py-4 @@PRIMARY@@ @@PRIMARY_HOVER@@ @@ON_PRIMARY@@ font-bold text-lg @@RADIUS@@ transition-all hover:-translate-y-0.5 shadow-lg`}
              >
                Confirm reservation
              </button>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
"""

FAQ = """import { useState } from 'react';
import { ChevronDown } from 'lucide-react';

const FAQS = [
  {
    q: 'Do you take walk-ins?',
    a: 'Absolutely -- about a third of our seating is kept for walk-ins. Weekends fill fast, so booking ahead is the safe bet.',
  },
  {
    q: 'Can you handle dietary requirements?',
    a: 'Yes. Vegetarian, vegan and gluten-free options are always on the menu, and the kitchen adapts dishes for allergies -- just tell us when you book.',
  },
  {
    q: 'Is there parking nearby?',
    a: 'Street parking is free after 6pm, and the Market Street garage is a two-minute walk with flat evening rates.',
  },
  {
    q: 'Do you host private events?',
    a: 'We do -- the back room seats 24 and can be booked with a set menu. Email us with your date and we will send the options.',
  },
];

export default function Faq() {
  const [open, setOpen] = useState(0);

  return (
    <section id="faq" className="py-24">
      <div className="max-w-3xl mx-auto px-6">
        <div className="text-center">
          <p className={`text-sm font-bold uppercase tracking-widest @@ACCENT_TEXT@@`}>FAQ</p>
          <h2 className="font-display mt-3 text-4xl md:text-5xl font-black tracking-tight @@HEAD@@">
            Questions, answered
          </h2>
        </div>

        <div className="mt-12 space-y-4">
          {FAQS.map((f, i) => (
            <div
              key={i}
              className={`reveal @@SURFACE@@ @@BORDER@@ border @@RADIUS@@ overflow-hidden shadow-sm animate-fade-up`}
              style={{ animationDelay: `${i * 90}ms` }}
            >
              <button
                onClick={() => setOpen(open === i ? -1 : i)}
                className={`w-full flex items-center justify-between gap-4 px-6 py-5 text-left font-display font-semibold @@HEAD@@ hover:@@ACCENT_TEXT@@ transition-colors`}
              >
                {f.q}
                <ChevronDown
                  className={`w-5 h-5 shrink-0 @@MUTED@@ transition-transform duration-300 ${
                    open === i ? 'rotate-180' : ''
                  }`}
                />
              </button>
              {open === i && (
                <p className={`px-6 pb-6 @@BODY@@ leading-relaxed`}>{f.a}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
"""

FEATURES = """import { Check, Sparkles, Users, Zap, Shield } from 'lucide-react';

const FEATURES = [
  { icon: Zap, title: 'Instant setup', body: 'Go from signup to working in under two minutes. No configuration, no credit card, no calls.' },
  { icon: Shield, title: 'Secure by default', body: 'Encryption in transit and at rest, granular permissions and a full audit trail on every plan.' },
  { icon: Users, title: 'Built for teams', body: 'Real-time collaboration with comments, mentions and shared views that keep everyone moving.' },
  { icon: Sparkles, title: 'Smart automation', body: 'Routine work runs itself with rules, triggers and templates you can set up in minutes.' },
];

export default function Features() {
  return (
    <section id="features" className="py-24 @@SURFACE2@@">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center max-w-2xl mx-auto">
          <p className={`text-sm font-bold uppercase tracking-widest @@ACCENT_TEXT@@`}>Why @@NAME@@</p>
          <h2 className="font-display mt-3 text-4xl md:text-5xl font-black tracking-tight @@HEAD@@">
            Everything you need. Nothing you don't.
          </h2>
          <p className={`mt-4 text-lg @@BODY@@`}>
            Four capabilities that replace a shelf of separate tools.
          </p>
        </div>

        <div className="mt-16 grid sm:grid-cols-2 gap-6">
          {FEATURES.map((f, i) => (
            <div
              key={i}
              className={`reveal group @@SURFACE@@ @@BORDER@@ border @@RADIUS@@ p-8 shadow-sm hover:shadow-xl transition-all duration-300 hover:-translate-y-1 animate-fade-up`}
              style={{ animationDelay: `${i * 100}ms` }}
            >
              <div className={`w-12 h-12 @@RADIUS@@ bg-gradient-to-br @@GRAD@@ flex items-center justify-center group-hover:scale-110 transition-transform`}>
                <f.icon className="w-6 h-6 @@ON_PRIMARY@@" />
              </div>
              <h3 className="font-display mt-6 text-xl font-bold @@HEAD@@">{f.title}</h3>
              <p className={`mt-2 @@BODY@@ leading-relaxed`}>{f.body}</p>
              <p className={`mt-4 text-sm font-semibold @@ACCENT_TEXT@@ flex items-center gap-1`}>
                <Check className="w-4 h-4" /> Included on every plan
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
"""

PRICING = """import { Check } from 'lucide-react';

const PLANS = [
  {
    name: 'Starter',
    price: 0,
    unit: '/mo',
    tagline: 'For getting started',
    features: ['Up to 3 projects', 'Community support', '1 GB storage', 'Basic analytics'],
    cta: 'Start free',
    highlighted: false,
  },
  {
    name: 'Pro',
    price: 24,
    unit: '/mo',
    tagline: 'For growing teams',
    features: ['Unlimited projects', 'Priority support', '100 GB storage', 'Advanced analytics', 'Custom domains'],
    cta: 'Start 14-day trial',
    highlighted: true,
  },
  {
    name: 'Enterprise',
    price: null,
    unit: '',
    tagline: 'For organizations at scale',
    features: ['Custom contracts & SLAs', 'Dedicated success manager', 'On-prem / private cloud', 'Security review & DPA'],
    cta: 'Talk to sales',
    highlighted: false,
  },
];

export default function Pricing() {
  return (
    <section id="pricing" className="py-24">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center max-w-2xl mx-auto">
          <p className={`text-sm font-bold uppercase tracking-widest @@ACCENT_TEXT@@`}>Pricing</p>
          <h2 className="font-display mt-3 text-4xl md:text-5xl font-black tracking-tight @@HEAD@@">
            Simple, honest plans
          </h2>
          <p className={`mt-4 text-lg @@BODY@@`}>Start free. Upgrade when it pays for itself.</p>
        </div>

        <div className="mt-16 grid md:grid-cols-3 gap-6 items-start">
          {PLANS.map((plan, i) => (
            <div
              key={i}
              className={`reveal relative p-8 @@RADIUS@@ @@BORDER@@ border transition-all duration-300 animate-fade-up ${
                plan.highlighted
                  ? `@@PRIMARY@@ @@ON_PRIMARY@@ shadow-2xl md:-translate-y-3 border-transparent`
                  : `@@SURFACE@@ shadow-sm hover:shadow-xl`
              }`}
              style={{ animationDelay: `${i * 100}ms` }}
            >
              {plan.highlighted && (
                <div className={`absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 @@ACCENT_BG@@ @@ACCENT_TEXT@@ text-[11px] font-bold tracking-wide rounded-full`}>
                  MOST POPULAR
                </div>
              )}
              <h3 className="font-display text-lg font-bold">{plan.name}</h3>
              <p className={`text-sm mt-1 ${plan.highlighted ? 'opacity-80' : '@@MUTED@@'}`}>{plan.tagline}</p>
              <div className="mt-6 flex items-baseline gap-1">
                {plan.price === null ? (
                  <span className="font-display text-4xl font-black">Custom</span>
                ) : (
                  <>
                    <span className="font-display text-4xl font-black">${plan.price}</span>
                    <span className={plan.highlighted ? 'opacity-70' : '@@MUTED@@'}>{plan.unit}</span>
                  </>
                )}
              </div>
              <ul className="mt-8 space-y-3">
                {plan.features.map((feat, j) => (
                  <li key={j} className="flex items-start gap-3 text-sm">
                    <Check className={`w-4 h-4 mt-0.5 shrink-0 ${plan.highlighted ? '' : '@@ACCENT_TEXT@@'}`} />
                    <span className={plan.highlighted ? 'opacity-90' : '@@BODY@@'}>{feat}</span>
                  </li>
                ))}
              </ul>
              <a
                href="#top"
                className={`mt-8 block text-center px-6 py-3.5 font-bold @@RADIUS@@ transition-all ${
                  plan.highlighted
                    ? `@@SURFACE@@ @@HEAD@@ hover:opacity-90`
                    : `@@PRIMARY@@ @@PRIMARY_HOVER@@ @@ON_PRIMARY@@`
                }`}
              >
                {plan.cta}
              </a>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
"""

# ---- SaaS-app exemplars (dashboard-side quality) ----

STAT_CARDS = """import { ArrowDownRight, ArrowUpRight, DollarSign, Users, Activity, ShoppingCart } from 'lucide-react';

const STATS = [
  { icon: DollarSign, label: 'Revenue', value: '$48,214', delta: '+12.4%', up: true },
  { icon: Users, label: 'Active users', value: '3,912', delta: '+5.1%', up: true },
  { icon: ShoppingCart, label: 'Orders', value: '1,287', delta: '+8.2%', up: true },
  { icon: Activity, label: 'Churn', value: '1.9%', delta: '-0.4%', up: false },
];

export default function StatCards() {
  return (
    <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
      {STATS.map((s, i) => (
        <div
          key={i}
          className={`@@SURFACE@@ @@BORDER@@ border @@RADIUS@@ p-5 shadow-sm hover:shadow-lg transition-shadow`}
        >
          <div className="flex items-center justify-between">
            <span className={`w-10 h-10 @@ACCENT_BG@@ @@ACCENT_TEXT@@ @@RADIUS@@ flex items-center justify-center`}>
              <s.icon className="w-5 h-5" />
            </span>
            <span className={`flex items-center gap-1 text-xs font-semibold ${
              s.up ? 'text-emerald-500' : 'text-red-500'
            }`}>
              {s.up ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
              {s.delta}
            </span>
          </div>
          <p className="font-display mt-4 text-2xl font-black @@HEAD@@">{s.value}</p>
          <p className={`text-sm @@MUTED@@`}>{s.label}</p>
        </div>
      ))}
    </div>
  );
}
"""

DATA_TABLE = """import { useState } from 'react';
import { ArrowUpDown, Filter, MoreHorizontal, Search } from 'lucide-react';

const ROWS = [
  { name: 'Acme Corp', owner: 'Maya Chen', status: 'Active', value: 12400, updated: '2h ago' },
  { name: 'Northwind', owner: 'Daniel Okafor', status: 'Trial', value: 0, updated: '5h ago' },
  { name: 'Lattice Labs', owner: 'Sofia Marino', status: 'Active', value: 8900, updated: '1d ago' },
  { name: 'Globex', owner: 'Liam Park', status: 'Churn risk', value: 4300, updated: '2d ago' },
  { name: 'Initech', owner: 'Ava Torres', status: 'Active', value: 15800, updated: '3d ago' },
];

const STATUS_STYLES = {
  Active: 'bg-emerald-50 text-emerald-700',
  Trial: 'bg-sky-50 text-sky-700',
  'Churn risk': 'bg-red-50 text-red-700',
};

export default function DataTable() {
  const [query, setQuery] = useState('');
  const rows = ROWS.filter((r) => r.name.toLowerCase().includes(query.toLowerCase()));

  return (
    <div className={`@@SURFACE@@ @@BORDER@@ border @@RADIUS@@ shadow-sm overflow-hidden`}>
      <div className="flex items-center justify-between gap-4 p-4 @@BORDER@@ border-b">
        <h3 className="font-display font-bold @@HEAD@@">Accounts</h3>
        <div className="flex items-center gap-2">
          <label className="relative">
            <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 @@MUTED@@`} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search..."
              className={`pl-9 pr-3 py-2 text-sm @@SURFACE2@@ @@BORDER@@ border @@RADIUS@@ @@HEAD@@ placeholder:@@MUTED@@ focus:outline-none focus:ring-2 focus:ring-current/30`}
            />
          </label>
          <button className={`px-3 py-2 text-sm @@BORDER@@ border @@RADIUS@@ @@BODY@@ hover:@@SURFACE2@@ transition-colors flex items-center gap-1.5`}>
            <Filter className="w-4 h-4" /> Filter
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className={`@@SURFACE2@@ text-left`}>
              <th className={`px-4 py-3 font-semibold @@MUTED@@`}>
                <span className="flex items-center gap-1">Name <ArrowUpDown className="w-3.5 h-3.5" /></span>
              </th>
              <th className={`px-4 py-3 font-semibold @@MUTED@@`}>Owner</th>
              <th className={`px-4 py-3 font-semibold @@MUTED@@`}>Status</th>
              <th className={`px-4 py-3 font-semibold @@MUTED@@ text-right`}>Value</th>
              <th className={`px-4 py-3 font-semibold @@MUTED@@`}>Updated</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className={`@@BORDER@@ border-t hover:@@SURFACE2@@ transition-colors`}>
                <td className={`px-4 py-3 font-semibold @@HEAD@@`}>{r.name}</td>
                <td className={`px-4 py-3 @@BODY@@`}>{r.owner}</td>
                <td className="px-4 py-3">
                  <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${STATUS_STYLES[r.status]}`}>
                    {r.status}
                  </span>
                </td>
                <td className={`px-4 py-3 text-right font-mono @@HEAD@@`}>
                  ${r.value.toLocaleString()}
                </td>
                <td className={`px-4 py-3 @@MUTED@@`}>{r.updated}</td>
                <td className="px-4 py-3 text-right">
                  <button className={`p-1.5 @@RADIUS@@ @@MUTED@@ hover:@@SURFACE2@@ transition-colors`}>
                    <MoreHorizontal className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className={`flex items-center justify-between px-4 py-3 @@BORDER@@ border-t text-sm @@MUTED@@`}>
        <span>Showing {rows.length} of {ROWS.length}</span>
        <div className="flex gap-2">
          <button className={`px-3 py-1.5 @@BORDER@@ border @@RADIUS@@ hover:@@SURFACE2@@ transition-colors`}>Previous</button>
          <button className={`px-3 py-1.5 @@BORDER@@ border @@RADIUS@@ hover:@@SURFACE2@@ transition-colors`}>Next</button>
        </div>
      </div>
    </div>
  );
}
"""

DASHBOARD = """import { Bell, Plus, Settings } from 'lucide-react';
import StatCards from './StatCards';
import DataTable from './DataTable';

export default function Dashboard() {
  return (
    <div className={`min-h-screen @@PAGE_BG@@ @@BODY@@`}>
      <header className={`sticky top-0 z-40 @@SURFACE@@/90 backdrop-blur-xl @@BORDER@@ border-b`}>
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <span className="font-display font-extrabold text-lg @@HEAD@@">@@NAME@@</span>
          <div className="flex items-center gap-2">
            <button className={`p-2 @@RADIUS@@ @@MUTED@@ hover:@@SURFACE2@@ transition-colors`}>
              <Bell className="w-5 h-5" />
            </button>
            <button className={`p-2 @@RADIUS@@ @@MUTED@@ hover:@@SURFACE2@@ transition-colors`}>
              <Settings className="w-5 h-5" />
            </button>
            <button className={`ml-2 px-4 py-2 @@PRIMARY@@ @@PRIMARY_HOVER@@ @@ON_PRIMARY@@ text-sm font-semibold @@RADIUS@@ transition-colors flex items-center gap-1.5`}>
              <Plus className="w-4 h-4" /> New
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-8">
        <div>
          <h1 className="font-display text-3xl font-black @@HEAD@@">Good morning, Maya</h1>
          <p className={`mt-1 @@MUTED@@`}>Here is what is happening across your workspace today.</p>
        </div>
        <StatCards />
        <DataTable />
      </main>
    </div>
  );
}
"""

TESTIMONIALS = """import { Quote, Star } from 'lucide-react';

const TESTIMONIALS = [
  {
    quote: 'The best evening we have had in years. Every plate felt considered, and the staff treated us like regulars from the first minute.',
    name: 'Maya Chen',
    role: 'Regular since 2019',
    initials: 'MC',
  },
  {
    quote: 'Booked the back room for our team dinner. Flawless service, a menu everyone could eat, and the wine pairing was spot on.',
    name: 'Daniel Okafor',
    role: 'Booked a private event',
    initials: 'DO',
  },
  {
    quote: 'I have eaten here a dozen times and the seasonal menu still surprises me. The tasting plate is worth every cent.',
    name: 'Sofia Marino',
    role: 'Food writer',
    initials: 'SM',
  },
];

export default function Testimonials() {
  return (
    <section id="testimonials" className="py-24 @@SURFACE2@@">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center max-w-2xl mx-auto">
          <p className={`text-sm font-bold uppercase tracking-widest @@ACCENT_TEXT@@`}>
            Guest stories
          </p>
          <h2 className="font-display mt-3 text-4xl md:text-5xl font-black tracking-tight @@HEAD@@">
            Don't take our word for it
          </h2>
        </div>

        <div className="mt-16 grid md:grid-cols-3 gap-6">
          {TESTIMONIALS.map((t, i) => (
            <figure
              key={i}
              className={`reveal @@SURFACE@@ @@BORDER@@ border @@RADIUS@@ p-8 shadow-sm hover:shadow-xl transition-shadow animate-fade-up`}
              style={{ animationDelay: `${i * 110}ms` }}
            >
              <Quote className={`w-6 h-6 @@ACCENT_TEXT@@`} />
              <blockquote className={`mt-4 @@BODY@@ leading-relaxed`}>
                {t.quote}
              </blockquote>
              <figcaption className="mt-6 flex items-center gap-3">
                <span
                  className={`w-10 h-10 @@RADIUS@@ bg-gradient-to-br @@GRAD@@ flex items-center justify-center text-xs font-bold @@ON_PRIMARY@@`}
                >
                  {t.initials}
                </span>
                <span>
                  <span className={`block font-display text-sm font-bold @@HEAD@@`}>
                    {t.name}
                  </span>
                  <span className={`block text-xs @@MUTED@@`}>{t.role}</span>
                </span>
              </figcaption>
              <div className="mt-4 flex gap-0.5">
                {[...Array(5)].map((_, s) => (
                  <Star key={s} className="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
                ))}
              </div>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
"""

CTA = """import { ArrowRight } from 'lucide-react';

export default function Cta() {
  return (
    <section id="visit" className="py-24">
      <div className="max-w-4xl mx-auto px-6">
        <div
          className={`reveal relative overflow-hidden @@RADIUS@@ bg-gradient-to-br @@GRAD@@ px-8 py-16 md:px-16 text-center shadow-2xl`}
        >
          <h2 className="font-display text-3xl md:text-5xl font-black tracking-tight @@ON_PRIMARY@@">
            Reserve your evening at @@NAME@@
          </h2>
          <p className="mt-4 text-lg max-w-xl mx-auto opacity-90 @@ON_PRIMARY@@">
            Tables go quickly on weekends -- book ahead and we will have the
            corner seat waiting.
          </p>
          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
            <a
              href="#reservations"
              className={`w-full sm:w-auto px-8 py-4 @@SURFACE@@ @@HEAD@@ font-bold @@RADIUS@@ hover:opacity-90 transition-opacity`}
            >
              Book a table <ArrowRight className="inline w-5 h-5 ml-1" />
            </a>
            <a
              href="#menu"
              className={`w-full sm:w-auto px-8 py-4 border font-bold @@RADIUS@@ @@ON_PRIMARY@@ border-current opacity-90 hover:opacity-100 transition-opacity`}
            >
              See the menu first
            </a>
          </div>
          <p className="mt-6 text-xs opacity-75 @@ON_PRIMARY@@">
            Open daily 12pm - 11pm · Walk-ins welcome
          </p>
        </div>
      </div>
    </section>
  );
}
"""

EXEMPLARS = {
    "Hero": HERO,
    "Menu": MENU,
    "Reservations": RESERVATIONS,
    "Faq": FAQ,
    "Features": FEATURES,
    "Pricing": PRICING,
    "Testimonials": TESTIMONIALS,
    "Cta": CTA,
    "StatCards": STAT_CARDS,
    "DataTable": DATA_TABLE,
    "Dashboard": DASHBOARD,
}
