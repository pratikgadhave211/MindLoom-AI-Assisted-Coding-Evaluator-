# Secure, searchable blog posts

The Flaskr blog allows people to write and manage posts. Users have reported that other people can modify their posts, and the index needs better search and navigation.

## Your task

1. Only a post's author may update or delete it. A different logged-in user must receive HTTP 403. A logged-out user must be redirected to login. Authors must still be able to manage their own posts.
2. Add a `q` query parameter to the blog index. Trim surrounding whitespace and search post titles and bodies case-insensitively. Empty or missing `q` shows all posts. Treat quotes, `%`, and `_` literally as search text.
3. Add a `page` query parameter with five posts per page. Order results newest first, breaking timestamp ties by descending post ID. Apply search before pagination and preserve `q` in the navigation links.
4. Invalid page numbers and pages beyond the last page return HTTP 404. An empty result set on page 1 returns HTTP 200. Existing login and post creation, update and deletion behavior must keep working.

Examples: `/?q=flask&page=2` shows the second page of matching posts; `/?q=%25` searches for a literal percent character.

Run the visible tests using `python -m pytest -q`. You may make any implementation that satisfies the behavior.
