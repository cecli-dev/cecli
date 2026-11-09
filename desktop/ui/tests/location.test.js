import assert from 'node:assert/strict';
import test from 'node:test';

import { active_agent_location, shorten_home_path } from '../src/core/format.js';

test('main workspace uses top-level cwd and branch', () => {
  const state = { cwd: '/home/alice/cecli', git_branch: 'main', subagents: [] };
  assert.equal(active_agent_location(state, '/home/alice'), '~/cecli • main');
});

test('selected sub-agent overrides the main workspace', () => {
  const state = {
    cwd: '/home/alice/cecli',
    git_branch: 'main',
    active_agent_session_id: 'child-1',
    subagents: [{ sessionId: 'child-1', cwd: '/home/alice/cecli-wt', gitBranch: 'feature/x' }],
  };
  assert.equal(active_agent_location(state, '/home/alice'), '~/cecli-wt • feature/x');
});

test('unmatched active id falls back to the main workspace', () => {
  const state = {
    cwd: '/home/alice/cecli',
    git_branch: 'main',
    active_agent_session_id: 'missing',
    subagents: [],
  };
  assert.equal(active_agent_location(state, '/home/alice'), '~/cecli • main');
});

test('missing branch is omitted', () => {
  assert.equal(active_agent_location({ cwd: '/home/alice/proj' }, '/home/alice'), '~/proj');
  assert.equal(active_agent_location({ cwd: '/tmp/proj', git_branch: '' }, ''), '/tmp/proj');
});

test('missing cwd leaves just the branch', () => {
  assert.equal(active_agent_location({ git_branch: 'dev' }), 'dev');
});

test('missing both parts yields an empty label', () => {
  assert.equal(active_agent_location({}), '');
  assert.equal(active_agent_location(undefined), '');
});

test('home shortening handles explicit and detected homes', () => {
  assert.equal(shorten_home_path('/home/alice/cecli', '/home/alice'), '~/cecli');
  assert.equal(shorten_home_path('/home/alice', '/home/alice'), '~');
  assert.equal(shorten_home_path('/home/bob/cecli'), '~/cecli');
  assert.equal(shorten_home_path('/root/project'), '~/project');
  assert.equal(shorten_home_path('/tmp/project', '/home/alice'), '/tmp/project');
  assert.equal(shorten_home_path('', '/home/alice'), '');
});

test('partial home prefixes are not shortened', () => {
  assert.equal(shorten_home_path('/home/alice2/project', '/home/alice'), '/home/alice2/project');
});