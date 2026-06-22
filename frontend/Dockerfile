FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .
ARG VITE_API_BASE=/api/v1
# SECURITY: VITE_* env vars are embedded in the JS bundle at build time.
# API_KEY here is used for server-side rate-limit identification, not as
# a secret. For true authentication, implement a server-side auth layer
# (e.g. JWT tokens) rather than embedding secrets in the frontend bundle.
ARG VITE_API_KEY=
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_API_KEY=$VITE_API_KEY
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
