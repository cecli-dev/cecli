import './styles/index.css';
import './styles/onboarding.css';
import 'katex/dist/katex.min.css';
import './components/cecli-app.js';

import { session } from './core/session.js';
import { init_theme } from './core/theme.js';

init_theme();
session.start();
