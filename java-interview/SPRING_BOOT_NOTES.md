# ☕ Spring Boot Internals — Principal Engineer Deep-Dive

> **A reference on Spring Boot, the DI container, AOP, transactions, security and production patterns**
> *Written for Staff/Principal Engineer interviews. Current as of October 2026: Spring Boot 4.1 (June 2026) and 4.0 (November 2025) on Spring Framework 7.0; Spring Boot 3.5 was the last 3.x line and its open-source support ended in June 2026.*

---

## Table of Contents

- [What Changed in Spring Boot 4 / Framework 7](#what-changed-in-spring-boot-4-framework-7)

1. [IoC Container & Dependency Injection](#1-ioc-container-dependency-injection)
2. [Bean Lifecycle & Post-Processors](#2-bean-lifecycle-post-processors)
3. [Auto-Configuration & Conditionals](#3-auto-configuration-conditionals)
4. [AOP — Aspect-Oriented Programming](#4-aop-aspect-oriented-programming)
5. [@Transactional — Propagation & Isolation](#5-transactional-propagation-isolation)
6. [Spring Data JPA & Hibernate](#6-spring-data-jpa-hibernate)
7. [Spring Security Internals](#7-spring-security-internals)
8. [Spring MVC — Request Processing](#8-spring-mvc-request-processing)
9. [Spring Boot Actuator & Observability](#9-spring-boot-actuator-observability)
10. [Testing Strategies](#10-testing-strategies)
11. [Production Patterns & Pitfalls](#11-production-patterns-pitfalls)
12. [Spring Boot Interview Questions](#12-spring-boot-interview-questions)

The [interview questions page](INTERVIEW_QUESTIONS.md) has longer worked answers on auto-configuration and the bean lifecycle (Q4) and on transactions (Q8).

---

## What Changed in Spring Boot 4 / Framework 7

!!! tip "30-second answer"
    Boot 4 / Framework 7 keep the **Java 17 baseline** (Java 25 recommended) and move to **Jakarta EE 11** (Servlet 6.1, JPA 3.2, Bean Validation 3.1), **Jackson 3**, **JSpecify** null-safety annotations, and a **modularized** Boot (one `spring-boot-<technology>` module per integration, with matching starters). Framework 7 adds first-class **API versioning**, **HTTP service client** registries, **`@Retryable`/`@ConcurrencyLimit`** in core, `BeanRegistrar`, `RestTestClient` and `JmsClient`. Undertow, `@MockBean`, Spock integration and the deprecated Spring Security "access" APIs are gone or moved out. Most of the production features people associate with "modern Spring Boot" (virtual threads, `RestClient`, structured logging, `@ServiceConnection`, CDS) arrived during 3.x.

| Area | What to know | Since |
|------|--------------|-------|
| Baselines | Java 17+ (25 recommended), Kotlin 2.2+, GraalVM 25+ for native images | Boot 4.0 |
| Jakarta EE 11 | Servlet 6.1 (Tomcat 11, Jetty 12.1), JPA 3.2 (Hibernate 7), Bean Validation 3.1. **Undertow is not supported** (no Servlet 6.1 support) | Boot 4.0 |
| Modularization | `spring-boot-autoconfigure` split into `spring-boot-<technology>` modules with packages `org.springframework.boot.<technology>`. Starters renamed: `spring-boot-starter-web` → `spring-boot-starter-webmvc`, `-aop` → `-aspectj`, `-web-services` → `-webservices`. `spring-boot-starter-classic` / `-test-classic` ease migration | Boot 4.0 |
| JSON | Jackson 3 (`tools.jackson` group and packages; annotations stay `com.fasterxml.jackson.annotation`). Jackson 2 support only in a deprecated module | Boot 4.0 |
| Null safety | JSpecify annotations (`org.jspecify.annotations.Nullable`) across Framework and Boot, replacing `org.springframework.lang` / JSR 305 | Framework 7 / Boot 4 |
| HTTP clients | `RestClient` (Framework 6.1 / Boot 3.2) and HTTP interface clients (`@HttpExchange`); Framework 7 adds `@ImportHttpServices` groups and Boot auto-configures them. `RestTemplate` is planned to be deprecated in Framework 7.1 and removed in 8.0 | 3.2 → 4.0 |
| API versioning | Map requests to controller methods by API version (header, query param, path or media type) in MVC and WebFlux | Framework 7 |
| Resilience | `@Retryable`, `@ConcurrencyLimit` with `@EnableResilientMethods`, and `RetryTemplate` in `spring-core` (`org.springframework.core.retry`) | Framework 7 |
| Testing | `@MockBean`/`@SpyBean` removed → `@MockitoBean`/`@MockitoSpyBean` (Framework 6.2+); `RestTestClient`; JUnit 6; JUnit 4 support removed from the TestContext framework | Boot 4.0 |
| Observability | Micrometer Observation API + Micrometer Tracing; new `spring-boot-starter-opentelemetry` exports metrics and traces over OTLP | Boot 3.0 → 4.0 |
| Virtual threads | `spring.threads.virtual.enabled=true` (Java 21+) switches Tomcat/Jetty request handling, `@Async`, scheduling and several clients to virtual threads | Boot 3.2 |
| Startup | AOT processing + GraalVM native images (Boot 3.0); CDS support (3.3); the JDK's AOT cache (Java 24+) works with Boot apps too | 3.x |
| Other 3.x features worth knowing | `@ServiceConnection` + Testcontainers/Docker Compose dev services (3.1), structured JSON logging `logging.structured.format.console=ecs` (3.4), graceful shutdown on by default (3.4) | 3.x |

---

## 1. IoC Container & Dependency Injection

!!! tip "30-second answer"
    The container reads **bean definitions** (from component scanning, `@Bean` methods, imports and auto-configuration), lets `BeanFactoryPostProcessor`s modify them, then instantiates singletons eagerly at `refresh()`, injecting dependencies and running `BeanPostProcessor`s, which is where proxies for `@Transactional`, `@Async` and aspects are created. Prefer **constructor injection**: dependencies are explicit, final and testable, and cycles fail fast.

### Container Hierarchy

```
BeanFactory (interface)
  └── The root container contract: getBean(), containsBean(), isSingleton()
  └── A plain DefaultListableBeanFactory creates singletons on first getBean()

ApplicationContext (extends BeanFactory)
  └── Pre-instantiates all non-lazy singletons during refresh()
  └── Event publication (ApplicationEventPublisher)
  └── Resource loading (ResourceLoader)
  └── Message i18n (MessageSource)
  └── Environment and profiles (EnvironmentCapable)

ConfigurableApplicationContext
  └── refresh(), close(), registerShutdownHook()

AbstractApplicationContext
  └── Template method implementation of refresh()

AnnotationConfigApplicationContext
  └── Plain Java-config context (@Configuration, @ComponentScan)

ServletWebServerApplicationContext (and its annotation-config subclass)
  └── What Spring Boot creates for a servlet web app: refresh() also creates and
      starts the embedded Tomcat/Jetty server (ReactiveWebServerApplicationContext
      for WebFlux)
```

### The `refresh()` Method — 13 Steps

```java
// AbstractApplicationContext.refresh(), simplified (Spring Framework 6/7):
@Override
public void refresh() throws BeansException, IllegalStateException {
    this.startupShutdownLock.lock();
    try {
        // 1. Prepare: startup date, active flag, validate required properties
        prepareRefresh();

        // 2. Obtain the bean factory (for annotation-based contexts the
        //    BeanDefinitions are registered later, by step 5)
        ConfigurableListableBeanFactory beanFactory = obtainFreshBeanFactory();

        // 3. Configure the factory: class loader, SpEL resolver, Aware-interface
        //    support (ApplicationContextAwareProcessor), environment beans
        prepareBeanFactory(beanFactory);
        try {
            // 4. Hook for subclasses (e.g. web contexts register request/session scopes)
            postProcessBeanFactory(beanFactory);

            // 5. Run BeanFactoryPostProcessors. The most important one,
            //    ConfigurationClassPostProcessor, parses @Configuration classes and
            //    processes @ComponentScan, @Import, @Bean and @PropertySource:
            //    this is where most BeanDefinitions (incl. auto-configuration) appear.
            invokeBeanFactoryPostProcessors(beanFactory);

            // 6. Instantiate and register BeanPostProcessors (@Autowired support,
            //    @PostConstruct support, auto-proxy creators...)
            registerBeanPostProcessors(beanFactory);

            // 7. MessageSource (i18n)
            initMessageSource();

            // 8. Event multicaster
            initApplicationEventMulticaster();

            // 9. Subclass hook: Spring Boot's web contexts CREATE THE WEB SERVER here
            onRefresh();

            // 10. Register ApplicationListener beans; publish early events
            registerListeners();

            // 11. Instantiate all remaining non-lazy singletons
            finishBeanFactoryInitialization(beanFactory);

            // 12. Lifecycle processor: start SmartLifecycle beans (Boot starts
            //     accepting web requests here), publish ContextRefreshedEvent
            finishRefresh();
        } catch (RuntimeException | Error ex) {
            // destroy already-created singletons, reset the active flag, rethrow
            destroyBeans();
            cancelRefresh(ex);
            throw ex;
        } finally {
            // 13. Clear reflection/metadata caches that are no longer needed
            resetCommonCaches();
        }
    } finally {
        this.startupShutdownLock.unlock();
    }
}
```

### Bean Scopes

| Scope | Description | Use Case |
|-------|-------------|----------|
| **singleton** | One instance per container (default) | Stateless services, repositories, clients |
| **prototype** | New instance per injection point / `getBean()`; the container does **not** manage its destruction | Stateful helper objects |
| **request** | One instance per HTTP request (web contexts) | Request-scoped data |
| **session** | One instance per HTTP session | User session data |
| **application** | One instance per `ServletContext` | Shared state across contexts in one web app |
| **websocket** | One instance per WebSocket session | WebSocket state |

Injecting a shorter-lived bean (request scope, prototype) into a singleton captures **one** instance forever. Fix with a scoped proxy (`@Scope(value = "request", proxyMode = ScopedProxyMode.TARGET_CLASS)`), `ObjectProvider<T>`, or `@Lookup` methods.

### Injection Types

```java
// ═══════════════════════════════════════════════════════════════
// 1. Constructor Injection (preferred; recommended by the Spring team)
// ═══════════════════════════════════════════════════════════════
@Service
public class UserService {
    private final UserRepository userRepository;
    private final EmailService emailService;

    // A single constructor needs no @Autowired (Spring 4.3+).
    // ✅ final fields, immutable after construction
    // ✅ plain `new UserService(mockRepo, mockEmail)` in unit tests
    // ✅ circular dependencies fail fast at startup instead of half-working
    // ✅ a long constructor is a visible smell: the class does too much
    public UserService(UserRepository userRepository, EmailService emailService) {
        this.userRepository = userRepository;
        this.emailService = emailService;
    }
}

// ═══════════════════════════════════════════════════════════════
// 2. Setter Injection
// ═══════════════════════════════════════════════════════════════
@Service
public class ReportService {
    private ReportFormatter formatter;

    @Autowired(required = false)          // good fit for OPTIONAL dependencies
    public void setFormatter(ReportFormatter formatter) {
        this.formatter = formatter;
    }
    // ⚠️ Can't be final; the object exists in a partially initialized state
    // ⚠️ Cycles through setters can be resolved by the container, but Spring Boot
    //    rejects circular references by default since 2.6
}

// ═══════════════════════════════════════════════════════════════
// 3. Field Injection (avoid in production code)
// ═══════════════════════════════════════════════════════════════
@Service
public class LegacyService {
    @Autowired
    private UserRepository userRepository;
    // ❌ Can't be final
    // ❌ Dependencies are hidden from the API
    // ❌ Tests need the container or reflection (@InjectMocks)
    // (Acceptable in test classes, e.g. @Autowired MockMvc.)
}

// ═══════════════════════════════════════════════════════════════
// 4. @Bean method parameters (Java config)
// ═══════════════════════════════════════════════════════════════
@Configuration(proxyBeanMethods = false)
public class AppConfig {
    @Bean
    public UserService userService(UserRepository userRepository, EmailService emailService) {
        return new UserService(userRepository, emailService);   // constructor injection
    }
}

// Choosing among several candidates of one type:
// @Primary on the default bean, @Qualifier("name") at the injection point,
// or inject List<T> / Map<String, T> / ObjectProvider<T> to get all or pick lazily.
```

---

## 2. Bean Lifecycle & Post-Processors

### Complete Bean Lifecycle (11 Steps)

```java
// Step 1: Instantiate: constructor (or factory method); constructor injection here
// Step 2: Populate: field and setter injection (AutowiredAnnotationBeanPostProcessor)
// Step 3: Aware callbacks: BeanNameAware, BeanClassLoaderAware, BeanFactoryAware
// Step 4: BeanPostProcessor.postProcessBeforeInitialization, for every BPP:
//         - ApplicationContextAware, EnvironmentAware etc. are invoked here
//           (ApplicationContextAwareProcessor)
//         - @PostConstruct runs here (CommonAnnotationBeanPostProcessor)
// Step 5: InitializingBean.afterPropertiesSet()
// Step 6: Custom init method (@Bean(initMethod = "init"))
// Step 7: BeanPostProcessor.postProcessAfterInitialization
//         → AOP PROXIES are created here (auto-proxy creators) for @Transactional,
//           @Cacheable, @Async, @Validated, @Retryable, aspects
//         → the returned proxy REPLACES the raw bean in the container
// Step 8: Ready. After ALL singletons exist: SmartInitializingSingleton callbacks,
//         then SmartLifecycle.start()
// ...
// On context close (reverse dependency order):
// Step 9:  @PreDestroy
// Step 10: DisposableBean.destroy()
// Step 11: Custom destroy method (@Bean(destroyMethod = ...); public close()/shutdown()
//          methods are inferred by default for @Bean)
```

### BeanPostProcessor — The Most Powerful Extension Point

```java
@Component
public class TimingBeanPostProcessor implements BeanPostProcessor {

    @Override
    public Object postProcessBeforeInitialization(Object bean, String beanName) {
        // Before @PostConstruct of this bean. Inspect or wrap; must return a bean.
        return bean;
    }

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) {
        // After init callbacks. Spring's own auto-proxy creators work at this point.
        if (bean instanceof MonitoredService) {
            return Proxy.newProxyInstance(
                bean.getClass().getClassLoader(),
                bean.getClass().getInterfaces(),
                (proxy, method, args) -> {
                    long start = System.nanoTime();
                    try {
                        return method.invoke(bean, args);
                    } catch (InvocationTargetException e) {
                        throw e.getCause();            // rethrow the real exception
                    } finally {
                        log.info("{} took {} µs", method.getName(), (System.nanoTime() - start) / 1000);
                    }
                });
            // Caveat: a JDK proxy only implements the interfaces, so anything that
            // injects the concrete class now fails. Prefer Spring AOP or
            // Micrometer's @Timed / @Observed for this in real code.
        }
        return bean;
    }
}
// BPPs are created early (step 6 of refresh()), so beans THEY depend on are created
// before all BPPs exist and miss some post-processing ("Bean 'x' is not eligible
// for getting processed by all BeanPostProcessors" in the log). Keep BPPs'
// dependencies minimal; declare them via static @Bean methods.
```

### BeanFactoryPostProcessor — Modify Bean Definitions Before Creation

```java
// Runs in step 5 of refresh(), after definitions are registered and BEFORE any
// regular bean is instantiated. Works on metadata (BeanDefinitions), not objects.
@Configuration(proxyBeanMethods = false)
public class LazyReportingConfig {

    // static: a BFPP must be instantiable before the rest of this @Configuration
    @Bean
    public static BeanFactoryPostProcessor lazyReportingBeans() {
        return factory -> {
            for (String name : factory.getBeanNamesForType(ReportGenerator.class, true, false)) {
                factory.getBeanDefinition(name).setLazyInit(true);   // create on first use
            }
        };
    }
}
// Real examples in Spring itself: ConfigurationClassPostProcessor (parses
// @Configuration), PropertySourcesPlaceholderConfigurer (resolves ${...}).
// Note getBeanNamesForType(type, includeNonSingletons, allowEagerInit=false): with
// allowEagerInit=true it could instantiate FactoryBeans too early.
```

### BeanDefinitionRegistryPostProcessor — Register New Bean Definitions

```java
// Runs before ordinary BeanFactoryPostProcessors and may ADD definitions.
// This is the mechanism behind @Configuration/@ComponentScan/@Import processing
// (ConfigurationClassPostProcessor implements it).
public class TenantClientsRegistrar implements BeanDefinitionRegistryPostProcessor {

    @Override
    public void postProcessBeanDefinitionRegistry(BeanDefinitionRegistry registry) {
        for (String tenant : List.of("acme", "globex")) {
            RootBeanDefinition bd = new RootBeanDefinition(TenantClient.class);
            bd.getConstructorArgumentValues().addGenericArgumentValue(tenant);
            registry.registerBeanDefinition(tenant + "Client", bd);
        }
    }

    @Override
    public void postProcessBeanFactory(ConfigurableListableBeanFactory factory) {
        // inherited from BeanFactoryPostProcessor; nothing to do here
    }
}

// Framework 7 adds a simpler, AOT-friendly API for programmatic registration:
public class TenantClients implements BeanRegistrar {
    @Override
    public void register(BeanRegistry registry, Environment env) {
        for (String tenant : env.getProperty("app.tenants", String[].class, new String[0])) {
            registry.registerBean(tenant + "Client", TenantClient.class,
                spec -> spec.supplier(ctx -> new TenantClient(tenant)));
        }
    }
}
// Activated with @Import(TenantClients.class) on a @Configuration class.
```

---

## 3. Auto-Configuration & Conditionals

!!! tip "30-second answer"
    `@EnableAutoConfiguration` (inside `@SpringBootApplication`) imports a deferred selector that loads candidate classes from every `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` on the classpath, orders them, filters them cheaply by class presence, and registers those whose `@Conditional`s match. Because they're processed after your configuration, `@ConditionalOnMissingBean` lets your beans win. Debug with `--debug` or `/actuator/conditions`.

### How Spring Boot Auto-Configuration Works

```java
// 1. @SpringBootApplication = @SpringBootConfiguration (a @Configuration)
//                           + @EnableAutoConfiguration
//                           + @ComponentScan (this package and below)

// 2. @EnableAutoConfiguration imports AutoConfigurationImportSelector
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@AutoConfigurationPackage
@Import(AutoConfigurationImportSelector.class)
public @interface EnableAutoConfiguration {}
// It's a DeferredImportSelector: it runs after all user @Configuration classes
// have been parsed.

// 3. Candidates come from
//    META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
//    in EVERY jar on the classpath (Boot 2.7+; Boot 3.0 dropped the old
//    META-INF/spring.factories EnableAutoConfiguration key).
//    In Boot 4 each technology module (spring-boot-jdbc, spring-boot-webmvc, ...)
//    ships its own imports file and its own package, e.g.
//    org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration
//    (Boot 3: org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration).

// 4. Before full evaluation, an AutoConfigurationImportFilter removes candidates
//    whose @ConditionalOnClass/@ConditionalOnBean/@ConditionalOnWebApplication
//    can't match, using precomputed metadata (no class loading). This keeps
//    startup fast despite hundreds of candidates.

// 5. A typical auto-configuration (simplified from JdbcTemplateAutoConfiguration):
@AutoConfiguration(after = DataSourceAutoConfiguration.class)
@ConditionalOnClass({ DataSource.class, JdbcTemplate.class })
@ConditionalOnSingleCandidate(DataSource.class)     // exactly one (or one @Primary) DataSource
@EnableConfigurationProperties(JdbcProperties.class)
public class JdbcTemplateAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean(JdbcOperations.class)   // back off if the user defined one
    public JdbcTemplate jdbcTemplate(DataSource dataSource, JdbcProperties properties) {
        JdbcTemplate template = new JdbcTemplate(dataSource);
        template.setFetchSize(properties.getTemplate().getFetchSize());
        return template;
    }
}
```

### @Conditional Mechanism

```java
// Every @ConditionalOn... annotation is backed by the Condition SPI:
@FunctionalInterface
public interface Condition {
    boolean matches(ConditionContext context, AnnotatedTypeMetadata metadata);
}

// ConditionContext gives access to:
// - the BeanDefinitionRegistry and BeanFactory (bean definitions registered so far)
// - the Environment (properties, profiles)
// - the ResourceLoader and ClassLoader

// @ConditionalOnClass / @ConditionalOnMissingClass
// The annotation's class attributes are read from bytecode metadata (ASM), so a
// missing class doesn't break parsing; the check then tries to load the class by
// name (without initializing it).

// @ConditionalOnBean / @ConditionalOnMissingBean
// Look at bean DEFINITIONS registered so far, so the result depends on ordering.
// Reliable in auto-configuration (processed after user config); unreliable in
// ordinary @Configuration classes.

// @ConditionalOnSingleCandidate: exactly one candidate, or one marked @Primary.

// @ConditionalOnProperty (simplified):
@Retention(RetentionPolicy.RUNTIME)
@Conditional(OnPropertyCondition.class)
public @interface ConditionalOnProperty {
    String prefix() default "";
    String[] name() default {};
    String havingValue() default "";        // "" = any value except "false"
    boolean matchIfMissing() default false;
}

@Bean
@ConditionalOnProperty(name = "myapp.feature.enabled", havingValue = "true")
public FeaturedService featuredService() {
    return new FeaturedService();
}
// Boot 3.5+: @ConditionalOnBooleanProperty("myapp.feature.enabled") says the same thing.

// Others: @ConditionalOnResource, @ConditionalOnWebApplication,
// @ConditionalOnExpression (SpEL), @ConditionalOnJava, @ConditionalOnThreading
// (virtual vs platform threads, Boot 3.2+), @ConditionalOnCloudPlatform.
//
// Keep custom conditions cheap and side-effect free (no network calls): they run
// at startup and, for native images/AOT, at BUILD time.
```

### Auto-Configuration Ordering

```java
// Ordering between auto-configurations:
// 1. @AutoConfiguration(before = ..., after = ...)  (also beforeName/afterName strings)
// 2. @AutoConfigureOrder (numeric)
// 3. @AutoConfigureBefore / @AutoConfigureAfter (older equivalents)
// Ordering affects only the order in which definitions are REGISTERED (which
// matters for @ConditionalOnBean), not bean creation order, which follows
// dependencies.

// Excluding auto-configuration:
@SpringBootApplication(exclude = DataSourceAutoConfiguration.class)
public class MyApplication {}
// or: spring.autoconfigure.exclude=<fully qualified class name>

// Seeing what happened:
// java -jar app.jar --debug       → CONDITIONS EVALUATION REPORT at startup
// GET /actuator/conditions        → same report at runtime
```

### Custom Auto-Configuration

```java
// A reusable starter = an autoconfigure module + a starter POM that depends on it.

// 1. The auto-configuration class
@AutoConfiguration
@ConditionalOnClass(AcmeClient.class)
@EnableConfigurationProperties(AcmeProperties.class)
public class AcmeAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public AcmeClient acmeClient(AcmeProperties properties) {
        return new AcmeClient(properties.url(), properties.timeout());
    }

    @Bean
    @ConditionalOnBooleanProperty("acme.monitoring.enabled")
    public AcmeMonitor acmeMonitor(AcmeClient client) {
        return new AcmeMonitor(client);
    }
}

// 2. Type-safe properties (records are supported with constructor binding)
@ConfigurationProperties(prefix = "acme")
public record AcmeProperties(
        @DefaultValue("http://localhost:8080") URI url,
        @DefaultValue("5s") Duration timeout) {}

// 3. Register it in the autoconfigure module:
//    src/main/resources/META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
//    containing one line:
//    com.acme.autoconfigure.AcmeAutoConfiguration
//
// 4. Add spring-boot-configuration-processor to generate metadata for IDE
//    completion of acme.* properties, and test with ApplicationContextRunner:
//    new ApplicationContextRunner()
//        .withConfiguration(AutoConfigurations.of(AcmeAutoConfiguration.class))
//        .withPropertyValues("acme.monitoring.enabled=true")
//        .run(ctx -> assertThat(ctx).hasSingleBean(AcmeMonitor.class));
```

---

## 4. AOP — Aspect-Oriented Programming

!!! tip "30-second answer"
    Spring AOP is **proxy-based**: callers get a proxy that runs the advice chain (transactions, caching, security, your aspects) and then calls the target. Spring Boot uses **CGLIB subclass proxies** by default; plain Spring uses JDK interface proxies when the bean has interfaces. Because advice lives in the proxy, **self-invocation** (`this.method()`) and `private`/`final` methods are never advised. Use AspectJ weaving if you need advice on those.

### How Spring AOP Works

```java
// 1. Auto-proxy creators (BeanPostProcessors) wrap beans that match an advisor
//    (@Transactional, @Cacheable, @Async, @PreAuthorize, @Aspect pointcuts)
// 2. A call through the proxy runs the interceptor chain, then the target method
// 3. Only calls that go THROUGH the proxy are advised:
//    - JDK proxy: public methods of the proxied interfaces
//    - CGLIB proxy: public and protected methods (and package-visible ones when
//      called from the same package); never private, final or static methods
// 4. @Aspect pointcuts in Spring AOP match method executions only (no field
//    access, constructor or static-method join points; that needs AspectJ)
```

### Proxy Mechanisms

```java
// JDK dynamic proxy (java.lang.reflect.Proxy):
// - implements all the bean's interfaces; InvocationHandler dispatches to the chain
// - only interface methods can be advised
// - the bean can only be injected by INTERFACE type

// CGLIB proxy (Spring's repackaged copy, org.springframework.cglib, in spring-core):
// - generates a SUBCLASS of the bean class at runtime (or at build time with AOT)
// - overrides non-final methods; final classes/methods can't be proxied
// - the constructor runs once for the target; Objenesis creates the proxy instance
//   without calling your constructor again

// Who picks:
@EnableAspectJAutoProxy                          // plain Spring default: proxyTargetClass = false
                                                 //   → JDK proxy if the bean has interfaces
@EnableAspectJAutoProxy(proxyTargetClass = true) // always CGLIB
// SPRING BOOT sets spring.aop.proxy-target-class=true by default (since 2.0), so
// Boot apps get CGLIB proxies even for beans that implement interfaces.
// Framework 7: @Proxyable on a bean, or a ProxyConfig bean, customizes this per bean.
```

### The Self-Invocation Problem

```java
@Service
public class UserService {

    @Transactional
    public void createUser(User user) {
        save(user);
        sendWelcomeEmail(user.getEmail());  // this.sendWelcomeEmail(): bypasses the proxy
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void sendWelcomeEmail(String email) {
        // Called via `this`, REQUIRES_NEW is ignored: this runs inside createUser's
        // transaction. Called from ANOTHER bean, it would suspend that transaction
        // and run in its own.
    }
}

// Why?
// - The bean other beans hold is the PROXY wrapping the real UserService
// - userService.createUser(...) → proxy → transaction begins → target.createUser()
// - Inside createUser(), `this` is the TARGET object, not the proxy
// - so this.sendWelcomeEmail() is a plain Java call: no advice

// FIX 1 (cleanest): move sendWelcomeEmail to another bean (EmailService) and inject it.
//        The need for a different transaction boundary usually means a different
//        responsibility anyway.

// FIX 2: programmatic transactions with explicit propagation
@Service
public class UserRegistration {
    private final TransactionTemplate tx;            // PROPAGATION_REQUIRED (default)
    private final TransactionTemplate newTx;         // PROPAGATION_REQUIRES_NEW

    public UserRegistration(PlatformTransactionManager tm) {
        this.tx = new TransactionTemplate(tm);
        this.newTx = new TransactionTemplate(tm);
        this.newTx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public void createUser(User user) {
        tx.executeWithoutResult(status -> {
            save(user);
            newTx.executeWithoutResult(inner -> recordEmailIntent(user.getEmail()));
            // reusing `tx` here would just JOIN the outer transaction
        });
    }
}

// FIX 3: self-injection through the proxy: @Lazy @Autowired UserService self;
//        (needs @Lazy/ObjectProvider since Boot forbids circular references by default;
//         works, but hides a design problem)
// FIX 4: AspectJ compile-time or load-time weaving: advice is woven into the class
//        itself, so self-calls (and private methods) are advised. More build setup.
```

### AspectJ Pointcut Expressions

```java
// EXECUTION: most common
@Pointcut("execution(public * com.myapp.service.*.*(..))")
// all public methods of classes directly in com.myapp.service

// WITHIN: all methods of types in a package (.. = including subpackages)
@Pointcut("within(com.myapp.service..*)")

// ANNOTATION on the method
@Pointcut("@annotation(org.springframework.transaction.annotation.Transactional)")

// ANNOTATION on the type
@Pointcut("@within(org.springframework.stereotype.Service)")

// BEAN name (Spring AOP only)
@Pointcut("bean(*Service)")

// COMBINING, and binding the annotation as an argument:
@Around("execution(* com.myapp.service..*(..)) && @annotation(timed)")
public Object around(ProceedingJoinPoint pjp, Timed timed) throws Throwable {
    return pjp.proceed();
}
```

### Creating a Custom Aspect

```java
@Aspect
@Component
public class LoggingAspect {
    private static final Logger log = LoggerFactory.getLogger(LoggingAspect.class);

    @Pointcut("execution(public * com.myapp.service..*(..))")
    public void serviceMethods() {}

    @Around("serviceMethods()")
    public Object logExecutionTime(ProceedingJoinPoint joinPoint) throws Throwable {
        String method = joinPoint.getSignature().toShortString();
        long start = System.nanoTime();
        try {
            return joinPoint.proceed();                 // invoke the target (or next advice)
        } finally {
            log.debug("{} took {} µs", method, (System.nanoTime() - start) / 1000);
        }
        // Don't log raw arguments/results by default: they often contain PII or
        // secrets, and toString() on entities can trigger lazy loading.
    }

    @AfterThrowing(pointcut = "serviceMethods()", throwing = "ex")
    public void logException(JoinPoint joinPoint, Exception ex) {
        log.warn("Exception in {}: {}", joinPoint.getSignature().toShortString(), ex.toString());
    }
}
// Ordering: @Order on the aspect class. Lower value = outer advice. Matters when
// combining with @Transactional (e.g. retry must wrap the transaction, not run
// inside it). Spring Boot 4 starter: spring-boot-starter-aspectj
// (spring-boot-starter-aop in Boot 3).
```

---

## 5. @Transactional — Propagation & Isolation

!!! tip "30-second answer"
    `TransactionInterceptor` (in the proxy) asks the `PlatformTransactionManager` to begin, join, suspend or savepoint according to **propagation**, binds the connection/EntityManager to the current thread, and commits or rolls back on return. Default rollback is on unchecked exceptions only. `REQUIRES_NEW` needs a **second connection**, which can deadlock a small pool. Transactions are thread-bound: they don't follow work into `@Async` methods or other threads. See [Question 8 in the interview questions](INTERVIEW_QUESTIONS.md#question-8-spring-transactions-propagation-isolation-and-transaction-management) for the full worked answer.

### Propagation Levels

```java
// REQUIRED (default): join the current transaction, or start one
@Transactional(propagation = Propagation.REQUIRED)

// REQUIRES_NEW: suspend the current transaction (if any), run in a NEW one that
// commits/rolls back independently, then resume. Needs a second connection.
@Transactional(propagation = Propagation.REQUIRES_NEW)

// NESTED: inside an existing transaction, set a JDBC SAVEPOINT and roll back to it
// on failure (the outer transaction can continue); with no transaction, like
// REQUIRED. Works with DataSourceTransactionManager / JdbcTemplate; JPA's
// JpaTransactionManager does not support savepoints for the EntityManager.
@Transactional(propagation = Propagation.NESTED)

// MANDATORY: must run inside an existing transaction, else IllegalTransactionStateException
@Transactional(propagation = Propagation.MANDATORY)

// NEVER: must NOT run inside a transaction, else exception
@Transactional(propagation = Propagation.NEVER)

// NOT_SUPPORTED: suspend any current transaction and run without one
@Transactional(propagation = Propagation.NOT_SUPPORTED)

// SUPPORTS: join if one exists, otherwise run non-transactionally
@Transactional(propagation = Propagation.SUPPORTS)
```

### Transaction Suspension Internals

```java
// When a REQUIRES_NEW method is called inside a transaction:
// 1. TransactionInterceptor → AbstractPlatformTransactionManager.getTransaction()
//    sees an existing transaction and REQUIRES_NEW
// 2. suspend():
//    a. unbind the current resources (ConnectionHolder, EntityManagerHolder) from
//       TransactionSynchronizationManager's thread-locals
//    b. suspend registered synchronizations
//    c. keep it all in a SuspendedResourcesHolder
//    (the first connection stays checked out, its transaction open, its locks held)
// 3. begin a new transaction: borrow a NEW connection, setAutoCommit(false), bind it
// 4. run the method
// 5. commit or roll back the new transaction; release its connection
// 6. resume(): rebind the suspended resources and synchronizations
//
// Consequences:
// - Each such call needs TWO connections at once. With a pool of 10 and 10
//   concurrent callers all holding their first connection, nobody gets a second:
//   all block until the pool's connectionTimeout (Hikari default 30 s), then fail.
// - If the inner transaction touches rows the outer one has locked, it waits for
//   the outer transaction, which waits for it: a self-deadlock until lock timeout.
```

### Isolation Levels

```java
// DEFAULT: whatever the database/connection uses
// (PostgreSQL, Oracle, SQL Server: READ COMMITTED; MySQL InnoDB: REPEATABLE READ)
@Transactional(isolation = Isolation.DEFAULT)

// READ_UNCOMMITTED: dirty reads allowed in theory (PostgreSQL treats it as READ COMMITTED)
// READ_COMMITTED: each statement sees data committed before it started (MVCC)
// REPEATABLE_READ:
//   - PostgreSQL: one snapshot for the whole transaction; updating a row changed
//     concurrently fails with a serialization error (SQLSTATE 40001) → retry
//   - MySQL: consistent snapshot for plain reads; locking reads and writes use
//     next-key/gap locks
// SERIALIZABLE:
//   - PostgreSQL: Serializable Snapshot Isolation, aborts one transaction of a
//     dangerous read/write dependency cycle → retry
//   - MySQL: plain SELECTs become locking reads
@Transactional(isolation = Isolation.REPEATABLE_READ)

// Isolation is applied only when Spring STARTS a transaction; a method that joins
// an existing one inherits that transaction's isolation.
```

### Read-Only Optimization

```java
@Transactional(readOnly = true)
public List<UserDto> findAllUsers() {
    // Hibernate (via JpaTransactionManager): flush mode MANUAL and a read-only
    // session: no dirty checking at commit and no snapshot copies of loaded entities
    // JDBC: Connection.setReadOnly(true); PgJDBC then runs the transaction READ ONLY
    // Replica routing is NOT automatic: it needs a routing DataSource
    // (e.g. AbstractRoutingDataSource keyed on
    //  TransactionSynchronizationManager.isCurrentTransactionReadOnly(), wrapped in a
    //  LazyConnectionDataSourceProxy so the decision happens after the tx starts)
    return userRepository.findAll().stream().map(UserDto::from).toList();
}
// Common pattern: @Transactional(readOnly = true) on the service class, and plain
// @Transactional on the methods that write.
```

### Common Transaction Pitfalls

```java
// ═══════════════════════════════════════════════════════════════
// PITFALL 1: @Transactional on private methods
// ═══════════════════════════════════════════════════════════════
@Service
public class MyService {
    @Transactional        // ← IGNORED: proxies can't intercept private methods
    private void doWork() { }
}
// Since Spring 6.0, protected and package-private methods ARE transactional with
// class-based (CGLIB) proxies; private methods never are.

// ═══════════════════════════════════════════════════════════════
// PITFALL 2: Methods not on the interface, with JDK proxies
// ═══════════════════════════════════════════════════════════════
@Service
public class MyService implements MyInterface {
    @Transactional        // not declared in MyInterface
    public void doWork() { }
}
// With JDK interface proxies (plain Spring, proxyTargetClass=false) callers can't
// even reach doWork() through the proxy. Spring Boot's default CGLIB proxies avoid
// this, but self-invocation still bypasses the proxy (section 4).

// ═══════════════════════════════════════════════════════════════
// PITFALL 3: Checked exceptions commit
// ═══════════════════════════════════════════════════════════════
@Transactional
public void process() throws BusinessException {
    // Default: roll back on RuntimeException and Error only.
    // A checked BusinessException leaves the transaction to COMMIT.
}
@Transactional(rollbackFor = BusinessException.class)
public void processAndRollBack() throws BusinessException { }

// ═══════════════════════════════════════════════════════════════
// PITFALL 4: Swallowed exceptions
// ═══════════════════════════════════════════════════════════════
@Transactional
public void process() {
    try {
        someMethod();
    } catch (Exception e) {
        // The interceptor sees normal completion → COMMIT of whatever happened.
        // To roll back while still handling it:
        TransactionAspectSupport.currentTransactionStatus().setRollbackOnly();
    }
}
// The reverse trap: an inner @Transactional (REQUIRED) bean method throws, which
// marks the SHARED transaction rollback-only; the outer method catches it and
// returns normally → UnexpectedRollbackException at commit.

// ═══════════════════════════════════════════════════════════════
// PITFALL 5: Remote calls inside transactions
// ═══════════════════════════════════════════════════════════════
// An HTTP call or message send inside @Transactional holds a DB connection (and
// locks) for its whole duration, and can't be rolled back. Do I/O outside the
// transaction; publish events after commit (@TransactionalEventListener(phase =
// AFTER_COMMIT)) or through a transactional outbox.
```

---

## 6. Spring Data JPA & Hibernate

### Entity State Transitions

```
                    new Entity()
                         │
                         ▼
                 ┌───────────────┐
                 │   TRANSIENT   │  not associated with any persistence context
                 └───────┬───────┘
                         │ persist()
                         ▼
                 ┌───────────────┐  remove()   ┌───────────────┐
                 │    MANAGED    │────────────►│    REMOVED    │──► DELETE at flush
                 │ (in the EM's  │◄────────────│ (scheduled    │
                 │  persistence  │  persist()  │  for delete)  │
                 │  context;     │             └───────────────┘
                 │  dirty-checked│
                 │  at flush)    │
                 └───┬───────▲───┘
   detach(), clear(),│       │ merge() copies the detached state into a
   EM closed,        │       │ MANAGED instance and returns THAT instance
   transaction ended │       │ (the argument itself stays detached)
                     ▼       │
                 ┌───────────┴───┐
                 │   DETACHED    │  has an id, but changes are not tracked
                 └───────────────┘
```

Spring Data's `save()` calls `persist()` for new entities and `merge()` otherwise ("new" = null id or null `@Version`, unless the entity implements `Persistable`). With assigned (non-generated) ids every `save()` is a `merge()`, which first SELECTs the row.

### Fetch Strategies

```java
@Entity
public class Order {
    @Id @GeneratedValue
    private Long id;

    // LAZY is the JPA default for @OneToMany/@ManyToMany
    @OneToMany(mappedBy = "order")
    private List<OrderItem> items;

    // EAGER is the JPA default for @ManyToOne/@OneToOne: make it LAZY explicitly.
    // Eager to-one associations load on every query of Order, often as extra
    // SELECTs (an N+1 you didn't ask for).
    @ManyToOne(fetch = FetchType.LAZY)
    private User user;

    // How lazy loading works:
    // - to-many: Hibernate's persistent collection wrappers (PersistentBag, ...)
    // - to-one:  a ByteBuddy-generated proxy subclass (Hibernate 5.3+)
    // Both need an open persistence context when first touched, or you get
    // LazyInitializationException.
}

// N+1:
// List<Order> orders = orderRepository.findAll();          // 1 query
// for (Order o : orders) o.getItems().size();              // +N queries

// FIX 1: fetch join (one query; Hibernate 6+ de-duplicates root entities)
@Query("select o from Order o join fetch o.items where o.status = :status")
List<Order> findWithItems(@Param("status") Status status);
// Don't combine collection fetch joins with pagination: Hibernate paginates IN
// MEMORY (warning HHH90003004). Page over ids first, then fetch.

// FIX 2: entity graph
@EntityGraph(attributePaths = "items")
List<Order> findByStatus(Status status);

// FIX 3: batch fetching: load collections for many owners per query
@OneToMany(mappedBy = "order")
@BatchSize(size = 50)
private List<OrderItem> items;
// or globally: spring.jpa.properties.hibernate.default_batch_fetch_size=50

// FIX 4: DTO projections for read paths (no entities, no lazy loading at all)
// record OrderSummary(Long id, String status, long itemCount) {}
// @Query("select new com.acme.OrderSummary(o.id, o.status, size(o.items)) from Order o")

// Detect: spring.jpa.properties.hibernate.generate_statistics=true in tests,
// SQL logging, or assert query counts in integration tests.
```

### Spring Data JPA Query Methods

```java
public interface UserRepository extends JpaRepository<User, Long> {

    // Derived queries (method name → JPQL)
    Optional<User> findByEmail(String email);
    List<User> findByNameAndAgeGreaterThan(String name, int age);
    List<User> findTop10ByOrderByCreatedAtDesc();
    boolean existsByEmail(String email);
    long countByStatus(UserStatus status);

    // JPQL
    @Query("select u from User u where u.email = :email")
    Optional<User> findByEmailCustom(@Param("email") String email);

    // Native SQL
    @Query(value = "select * from users u where u.email = :email", nativeQuery = true)
    Optional<User> findByEmailNative(@Param("email") String email);

    // Bulk update: bypasses the persistence context. Clear it afterwards so loaded
    // entities don't show stale values; needs a transaction.
    @Transactional
    @Modifying(clearAutomatically = true)
    @Query("update User u set u.status = :status where u.lastLogin < :date")
    int deactivateInactiveUsers(@Param("date") LocalDate date, @Param("status") UserStatus status);

    // Interface projection: selects only the needed columns
    interface UserSummary {
        String getName();
        String getEmail();
    }
    List<UserSummary> findAllProjectedBy();
}
```

### Locking Strategies

```java
// OPTIMISTIC LOCKING: opt-in by adding a @Version attribute
@Entity
public class Account {
    @Id
    private Long id;
    private BigDecimal balance;

    @Version
    private Long version;   // UPDATE ... SET version = version + 1 WHERE id = ? AND version = ?
    // 0 rows updated → ObjectOptimisticLockingFailureException → retry or report a conflict
}

// PESSIMISTIC LOCKING
public interface AccountRepository extends JpaRepository<Account, Long> {

    @Lock(LockModeType.PESSIMISTIC_WRITE)   // SELECT ... FOR UPDATE
    @Query("select a from Account a where a.id = :id")
    Optional<Account> findByIdForUpdate(@Param("id") Long id);

    @Lock(LockModeType.PESSIMISTIC_READ)    // SELECT ... FOR SHARE (PostgreSQL)
    @Query("select a from Account a where a.id = :id")
    Optional<Account> findByIdForShare(@Param("id") Long id);
}
// Set a lock timeout (jakarta.persistence.lock.timeout hint) and lock rows in a
// consistent order to avoid deadlocks.
```

### Hibernate Common Pitfalls

```java
// ═══════════════════════════════════════════════════════════════
// PITFALL 1: LazyInitializationException
// ═══════════════════════════════════════════════════════════════
@Transactional(readOnly = true)
public Order getOrder(Long id) {
    return orderRepository.findById(id).orElseThrow();
}   // persistence context closes here
// later, in the controller or the JSON serializer:
// order.getItems().size();   // ← LazyInitializationException (with OSIV disabled)

// Fixes: fetch what the use case needs inside the service (fetch join,
// @EntityGraph), or return a DTO built inside the transaction.
// Open Session In View hides the problem: spring.jpa.open-in-view is TRUE by
// default in Spring Boot (still in 4.x; Boot logs a warning). Set it to false.

// ═══════════════════════════════════════════════════════════════
// PITFALL 2: Serializing entities directly
// ═══════════════════════════════════════════════════════════════
@Entity
public class User {
    @OneToMany(mappedBy = "user")
    @JsonIgnore                     // stops Jackson from walking the lazy collection
    private List<Order> orders;

    public int getOrderCount() {    // ...but Jackson still calls this getter: one
        return orders.size();       // lazy load per serialized User = N+1
    }
}
// Fix: return DTOs/records from controllers; compute counts in the query.
// Entities as API payloads also leak schema details and invite over-posting.

// ═══════════════════════════════════════════════════════════════
// PITFALL 3: equals/hashCode on entities
// ═══════════════════════════════════════════════════════════════
// Generated ids are null until persist, so id-based equals/hashCode changes over
// the entity's life and breaks HashSets. Use a natural/business key, or id-based
// equals with a constant hashCode. Lombok @Data on entities is a common trap
// (also triggers lazy loading in toString/hashCode).
```

---

## 7. Spring Security Internals

!!! tip "30-second answer"
    Spring Security is a servlet `Filter` (`DelegatingFilterProxy` → `FilterChainProxy`) that picks the first matching `SecurityFilterChain` and runs its ordered filters: load the `SecurityContext`, authenticate (form login, bearer token, basic...), then `ExceptionTranslationFilter` and finally `AuthorizationFilter`, which asks an `AuthorizationManager` for a decision. Authentication results live in the thread-bound `SecurityContextHolder`. Spring Security 7 (with Boot 4) removed the legacy `authorizeRequests`/`and()` DSL and moved the old `AccessDecisionManager` API into a separate legacy module.

### Security Filter Chain

```java
// Servlet container
//   → DelegatingFilterProxy ("springSecurityFilterChain")
//     → FilterChainProxy: picks the FIRST SecurityFilterChain whose matcher matches
//       → that chain's filters, in a fixed order (simplified):

// 1. SecurityContextHolderFilter (replaced SecurityContextPersistenceFilter, removed in 6.0)
//    - Lazily loads the SecurityContext from the SecurityContextRepository
//      (HTTP session by default; nothing for stateless APIs)
//    - Does NOT save it automatically any more: authentication mechanisms save
//      explicitly (SecurityContextRepository.saveContext) when they authenticate
//    - Clears the thread-local after the request

// 2. CsrfFilter: for state-changing requests, checks the CSRF token
//    (cookie/session-based apps; usually disabled for pure bearer-token APIs)

// 3. LogoutFilter

// 4. Authentication filters, e.g.:
//    - BearerTokenAuthenticationFilter (OAuth2 resource server): extracts the JWT,
//      AuthenticationManager → JwtAuthenticationProvider validates it
//    - UsernamePasswordAuthenticationFilter (form login POST /login)
//    - BasicAuthenticationFilter
//    On success: SecurityContextHolder.getContext().setAuthentication(...)

// 5. ExceptionTranslationFilter
//    - AuthenticationException, or AccessDeniedException for an anonymous user
//      → AuthenticationEntryPoint (401 / redirect to login)
//    - AccessDeniedException for an authenticated user → AccessDeniedHandler (403)

// 6. AuthorizationFilter (replaced FilterSecurityInterceptor)
//    - Asks the AuthorizationManager built from authorizeHttpRequests(...) rules
//    - Denied → AccessDeniedException → handled by step 5
```

### Authentication Flow

```java
// AuthenticationManager (usually ProviderManager) tries each AuthenticationProvider
// that supports the token type:
//   - DaoAuthenticationProvider: UserDetailsService + PasswordEncoder
//   - JwtAuthenticationProvider: JwtDecoder (signature, exp/nbf, issuer, audience)
//     + a converter from claims to GrantedAuthorities
//   - your own provider
// Result: an authenticated Authentication (principal + authorities) stored in the
// SecurityContext, which is held in SecurityContextHolder (a ThreadLocal by default).
//
// Authorization:
//   - URL rules → AuthorizationFilter → AuthorizationManager
//     (e.g. AuthorityAuthorizationManager for hasRole/hasAuthority)
//   - Method security: @EnableMethodSecurity + @PreAuthorize("hasRole('ADMIN')")
//     or @PreAuthorize("@guard.canEdit(#id, authentication)"), implemented with
//     AOP interceptors and AuthorizationManagers
//   - The legacy AccessDecisionManager/AccessDecisionVoter API (and
//     @EnableGlobalMethodSecurity) lives in the separate spring-security-access
//     module in Security 7, for migration only.
//
// Threads: the SecurityContext is thread-bound, so it doesn't follow @Async or
// executor tasks unless you propagate it (DelegatingSecurityContextExecutor, or
// Micrometer context propagation).
```

### Security Configuration (Java Config)

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
public class SecurityConfig {

    @Bean
    public SecurityFilterChain apiChain(HttpSecurity http) throws Exception {
        http
            .securityMatcher("/api/**")
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/api/public/**").permitAll()
                .requestMatchers("/api/admin/**").hasRole("ADMIN")
                .requestMatchers("/api/user/**").hasAnyRole("USER", "ADMIN")
                .anyRequest().authenticated())
            .oauth2ResourceServer(oauth2 -> oauth2
                .jwt(jwt -> jwt.jwtAuthenticationConverter(jwtAuthenticationConverter())))
            .sessionManagement(session -> session
                .sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .csrf(csrf -> csrf.disable())   // stateless bearer-token API: no cookies to forge
            .exceptionHandling(ex -> ex
                .authenticationEntryPoint((req, resp, authEx) ->
                    resp.sendError(HttpServletResponse.SC_UNAUTHORIZED))
                .accessDeniedHandler((req, resp, deniedEx) ->
                    resp.sendError(HttpServletResponse.SC_FORBIDDEN)));
        return http.build();
    }

    @Bean
    JwtAuthenticationConverter jwtAuthenticationConverter() {
        JwtGrantedAuthoritiesConverter authorities = new JwtGrantedAuthoritiesConverter();
        authorities.setAuthoritiesClaimName("roles");
        authorities.setAuthorityPrefix("ROLE_");
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(authorities);
        return converter;
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        // Stores "{bcrypt}..." style hashes, so the algorithm can be upgraded later
        return PasswordEncoderFactories.createDelegatingPasswordEncoder();
    }
}
// The JwtDecoder is auto-configured by Spring Boot from
//   spring.security.oauth2.resourceserver.jwt.issuer-uri=https://auth.example.com/
// (discovers the JWKS endpoint and validates the issuer). Define your own
// JwtDecoder bean only to customize validation (audience, clock skew).
```

---

## 8. Spring MVC — Request Processing

### Request Lifecycle

```
HTTP Request
    │
    ▼
Tomcat connector: acceptor/poller threads → request handed to a worker thread
    (a platform thread from the pool, server.tomcat.threads.max = 200 by default,
     or a new virtual thread per request with spring.threads.virtual.enabled=true)
    │
    ▼
Servlet filter chain (ordered), e.g. in a Boot app:
    ├── CharacterEncodingFilter
    ├── ServerHttpObservationFilter (metrics + tracing for http.server.requests)
    ├── FormContentFilter
    ├── RequestContextFilter
    └── DelegatingFilterProxy → Spring Security's FilterChainProxy
    │
    ▼
DispatcherServlet (front controller)
    ├── 1. Multipart check (MultipartResolver)
    ├── 2. LocaleResolver
    ├── 3. HandlerMapping: find the handler + its interceptors
    │      ├── RequestMappingHandlerMapping (@RequestMapping, incl. API version
    │      │   conditions in Framework 7)
    │      ├── RouterFunctionMapping (functional endpoints)
    │      └── SimpleUrlHandlerMapping (static resources, explicit mappings)
    ├── 4. HandlerInterceptor.preHandle() for each interceptor (can short-circuit)
    ├── 5. HandlerAdapter invokes the handler
    │      └── RequestMappingHandlerAdapter
    │          ├── resolve arguments (HandlerMethodArgumentResolver):
    │          │   @PathVariable, @RequestParam, @RequestBody (HttpMessageConverter),
    │          │   @Valid validation, Principal, custom resolvers
    │          ├── invoke the controller method
    │          └── handle the return value (HandlerMethodReturnValueHandler):
    │              @ResponseBody / ResponseEntity → HttpMessageConverter (Jackson),
    │              view name / ModelAndView → view rendering
    ├── 6. HandlerInterceptor.postHandle() (not called if the handler threw)
    ├── 7. Exceptions → HandlerExceptionResolvers:
    │      ExceptionHandlerExceptionResolver (@ExceptionHandler/@ControllerAdvice),
    │      ResponseStatusExceptionResolver, DefaultHandlerExceptionResolver;
    │      ProblemDetail (RFC 9457) bodies via spring.mvc.problemdetails.enabled
    ├── 8. View rendering, if any (ViewResolver)
    └── 9. HandlerInterceptor.afterCompletion() (always, even on exceptions)

(Theme support, ThemeResolver, was removed in Framework 7. HiddenHttpMethodFilter
 is off by default in Boot since 2.2.)
```

### HandlerMethodArgumentResolver — Custom

```java
public class CurrentUserArgumentResolver implements HandlerMethodArgumentResolver {

    @Override
    public boolean supportsParameter(MethodParameter parameter) {
        return parameter.hasParameterAnnotation(CurrentUser.class)
            && parameter.getParameterType().equals(UserPrincipal.class);
    }

    @Override
    public Object resolveArgument(MethodParameter parameter,
                                  ModelAndViewContainer mavContainer,
                                  NativeWebRequest webRequest,
                                  WebDataBinderFactory binderFactory) {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !(auth.getPrincipal() instanceof UserPrincipal user)) {
            return null;
        }
        return user;
    }
}

// Registering it: being a @Component is NOT enough; add it to MVC config.
@Configuration
public class WebConfig implements WebMvcConfigurer {
    @Override
    public void addArgumentResolvers(List<HandlerMethodArgumentResolver> resolvers) {
        resolvers.add(new CurrentUserArgumentResolver());
    }
}

@GetMapping("/profile")
public UserProfile profile(@CurrentUser UserPrincipal user) {
    return userService.getProfile(user.id());
}
// Spring Security already ships this: @AuthenticationPrincipal UserPrincipal user.
```

### API Versioning (Framework 7)

```java
// application.properties (Boot 4): read the version from a request header
// spring.mvc.apiversion.use.header=API-Version
// spring.mvc.apiversion.default=1.0

@RestController
@RequestMapping("/orders")
public class OrderController {
    @GetMapping(path = "/{id}", version = "1.0")
    public OrderV1 getV1(@PathVariable long id) { /* ... */ return null; }

    @GetMapping(path = "/{id}", version = "2.0+")     // 2.0 and later
    public OrderV2 getV2(@PathVariable long id) { /* ... */ return null; }
}
// Versions can also come from a query parameter, a path segment or the media type;
// deprecated versions can be advertised with Deprecation/Sunset headers.
```

---

## 9. Spring Boot Actuator & Observability

!!! tip "30-second answer"
    Actuator exposes operational endpoints (health, metrics, info, loggers...). Only `health` is exposed over HTTP by default; expose more deliberately and secure them. Instrumentation is built on the **Micrometer Observation API**: one instrumentation point produces metrics (Micrometer, e.g. Prometheus) **and** traces (Micrometer Tracing with an OpenTelemetry or Brave bridge). Boot 4 adds `spring-boot-starter-opentelemetry` for OTLP export of metrics and traces. Use Kubernetes liveness/readiness health groups, and keep liveness free of dependency checks.

### Actuator Endpoints

```java
// Exposure: only /actuator/health over HTTP by default (Boot 2.5+). Others via
//   management.endpoints.web.exposure.include=health,info,prometheus,metrics
// Serve them on a separate port if possible: management.server.port=8081
//
// /actuator/health         — health (groups: /health/liveness, /health/readiness)
// /actuator/info           — build/git/app info
// /actuator/metrics        — browse Micrometer meters
// /actuator/prometheus     — Prometheus scrape format
// /actuator/env            — environment (values masked by default; sensitive)
// /actuator/configprops    — @ConfigurationProperties (masked by default)
// /actuator/beans          — beans in the context
// /actuator/conditions     — auto-configuration report
// /actuator/loggers        — view and CHANGE log levels at runtime
// /actuator/threaddump     — thread dump
// /actuator/heapdump       — heap dump (large and full of secrets: never public)
// /actuator/httpexchanges  — recent HTTP exchanges (needs an HttpExchangeRepository
//                            bean; was /httptrace before Boot 3)
// /actuator/startup        — startup steps (with BufferingApplicationStartup)
// /actuator/sbom           — software bill of materials (Boot 3.3+)
```

### Custom Health Indicator

```java
@Component
public class PaymentGatewayHealthIndicator implements HealthIndicator {
    private final PaymentGatewayClient client;

    public PaymentGatewayHealthIndicator(PaymentGatewayClient client) {
        this.client = client;
    }

    @Override
    public Health health() {
        try {
            Duration latency = client.ping(Duration.ofMillis(500));   // short timeout
            return Health.up().withDetail("latencyMs", latency.toMillis()).build();
        } catch (Exception e) {
            return Health.down(e).build();
        }
    }
}
// Boot already provides indicators for DataSources, Redis, Kafka, disk space, etc.
//
// Kubernetes:
// - management.endpoint.health.probes.enabled=true (automatic on Kubernetes)
//   gives /actuator/health/liveness and /actuator/health/readiness
// - LIVENESS should reflect only the app's own state: a failing liveness probe
//   RESTARTS the pod, so a database outage in liveness turns into a restart storm
// - Put downstream dependencies in READINESS (or nowhere), deliberately:
//   management.endpoint.health.group.readiness.include=readinessState,db
// - Health checks run on every probe: keep them cheap and time-bounded
```

### Micrometer, Tracing & OpenTelemetry

```java
// Boot auto-instruments: HTTP server/client requests (http.server.requests,
// http.client.requests), JVM (memory, GC, threads), HikariCP, Tomcat, Kafka,
// executors, caches... so you rarely need a hand-written request counter.

@Service
public class ItemService {
    private final ItemRepository repository;
    private final Counter importedItems;

    public ItemService(ItemRepository repository, MeterRegistry registry) {
        this.repository = repository;
        this.importedItems = Counter.builder("items.imported")
            .description("Items imported from the catalog feed")
            .tag("source", "catalog")              // LOW-cardinality tags only
            .register(registry);
    }

    // One annotation → a timer metric AND a trace span (needs the
    // ObservedAspect bean / spring-boot-starter-aspectj)
    @Observed(name = "items.import", contextualName = "import-items")
    public void importItems(List<Item> items) {
        repository.saveAll(items);
        importedItems.increment(items.size());
    }
}
// Latency percentiles: prefer histograms that the backend aggregates
//   management.metrics.distribution.percentiles-histogram.http.server.requests=true
// over client-side publishPercentiles(...), which can't be aggregated across instances.
// Never use user IDs, raw URLs or other unbounded values as tag values: each distinct
// value is a new time series (memory leak in the app and cost in the backend).

// Tracing:
// - Micrometer Tracing with the OpenTelemetry bridge (or Brave) propagates W3C
//   traceparent headers through RestClient/WebClient/Kafka and puts traceId/spanId
//   into the logging MDC
// - management.tracing.sampling.probability=0.1 (default 0.1)
// - Boot 4: spring-boot-starter-opentelemetry brings OTLP export for metrics and
//   traces (endpoints configured under management.otlp.* / management.opentelemetry.*;
//   check the property names for your Boot version, they moved between 3.x and 4.x)
// - Context propagation across threads (@Async, executors, Reactor) uses the
//   Micrometer context-propagation library
//
// Logs: structured JSON logging is built in since Boot 3.4:
//   logging.structured.format.console=ecs   (or logstash, gelf)
```

---

## 10. Testing Strategies

!!! tip "30-second answer"
    Most tests should be plain unit tests (constructor injection makes them trivial). Use **slices** (`@WebMvcTest`, `@DataJpaTest`, `@JsonTest`...) to test one layer with a minimal context, and a few `@SpringBootTest`s with **real dependencies in Testcontainers** for integration. Replace beans with `@MockitoBean` (Boot 4 removed `@MockBean`). Keep the number of distinct test contexts small, because Spring caches and reuses identical contexts and every new combination costs a full startup.

### Unit Testing with Mockito

```java
@ExtendWith(MockitoExtension.class)
class UserServiceTest {

    @Mock
    private UserRepository userRepository;

    @Mock
    private EmailService emailService;

    @InjectMocks
    private UserService userService;   // or simply: new UserService(userRepository, emailService)

    @Test
    void createUser_savesAndSendsEmail() {
        User user = new User("test@example.com", "Test");
        when(userRepository.save(any(User.class))).thenReturn(user);

        User result = userService.createUser(user);

        assertThat(result).isEqualTo(user);
        verify(userRepository).save(user);
        verify(emailService).sendWelcomeEmail("test@example.com");
    }

    @Test
    void createUser_duplicateEmail_throws() {
        when(userRepository.existsByEmail("existing@example.com")).thenReturn(true);

        assertThatThrownBy(() -> userService.createUser(new User("existing@example.com", "Test")))
            .isInstanceOf(DuplicateEmailException.class);

        verify(userRepository, never()).save(any());
    }
}
```

### Slice and Integration Testing

```java
// Web slice: controllers, advice, converters, MockMvc; no services/repositories
@WebMvcTest(UserController.class)
class UserControllerTest {
    @Autowired MockMvc mockMvc;              // or MockMvcTester (AssertJ-style, Boot 3.4+)
    @MockitoBean UserService userService;    // Framework 6.2+; replaces Boot's @MockBean

    @Test
    void getUser_returnsJson() throws Exception {
        when(userService.find(1L)).thenReturn(new UserDto(1L, "alice@example.com"));

        mockMvc.perform(get("/api/users/1"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.email").value("alice@example.com"));
    }
}
// In Boot 4 the slice annotations live in per-technology test modules
// (e.g. spring-boot-webmvc-test); spring-boot-starter-test-classic brings the
// old all-in-one set back during migration.

// Full context with a real server and a real HTTP client:
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient   // Boot 4 / Framework 7 RestTestClient
class UserApiIT {
    @Autowired RestTestClient client;

    @Test
    void createUser_returnsCreated() {
        client.post().uri("/api/users")
            .contentType(MediaType.APPLICATION_JSON)
            .body("""
                {"email": "new@example.com", "name": "New User"}
                """)
            .exchange()
            .expectStatus().isCreated();
    }
}
// (MockMvc needs no real port: use the default MOCK web environment with
//  @AutoConfigureMockMvc; RANDOM_PORT is for tests over real HTTP.)
```

### Database Testing with Testcontainers

```java
@SpringBootTest
@Testcontainers
class UserRepositoryIT {

    // @ServiceConnection (Boot 3.1+) derives spring.datasource.* from the container:
    // no @DynamicPropertySource boilerplate.
    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17-alpine");

    @Autowired
    UserRepository userRepository;

    @Test
    void findByEmail_findsSavedUser() {
        userRepository.save(new User("test@example.com", "Test"));

        assertThat(userRepository.findByEmail("test@example.com"))
            .get()
            .extracting(User::getName)
            .isEqualTo("Test");
    }
}
// The same container definitions can power local development:
// SpringApplication.from(App::main).with(TestcontainersConfig.class).run(args),
// or Docker Compose support (spring-boot-docker-compose) for `./mvnw spring-boot:run`.
//
// Use @DataJpaTest + @AutoConfigureTestDatabase(replace = NONE) for a JPA slice
// against the real database instead of an in-memory H2 that behaves differently.
```

---

## 11. Production Patterns & Pitfalls

### Graceful Shutdown

```java
// Since Spring Boot 3.4, graceful shutdown is the DEFAULT for all embedded servers:
//   server.shutdown=graceful                          (default; "immediate" to opt out)
//   spring.lifecycle.timeout-per-shutdown-phase=30s   (default 30s)
//
// On SIGTERM: the server stops accepting new requests, in-flight requests get up
// to the timeout to finish, then the context closes (@PreDestroy, pools closed).
//
// On Kubernetes, also:
// - flip readiness to OUT_OF_SERVICE first (Boot does this on shutdown) and let
//   endpoints update: a short preStop sleep (e.g. 5-10 s) avoids traffic arriving
//   after the server stopped listening
// - terminationGracePeriodSeconds > preStop + shutdown timeout
// - make consumers (Kafka, queues) stop polling and commit/ack before exit
```

### Common Production Pitfalls

```java
// ═══════════════════════════════════════════════════════════════
// PITFALL 1: @ComponentScan replacing the default scan
// ═══════════════════════════════════════════════════════════════
@SpringBootApplication
@ComponentScan("com.otherpackage")   // REPLACES the default scan of this package
public class App {}
// Fix: put the main class in a root package above everything; to add packages use
// @SpringBootApplication(scanBasePackages = {"com.myapp", "com.otherpackage"}),
// or better, @Import the configuration you need.

// ═══════════════════════════════════════════════════════════════
// PITFALL 2: Scattered @Value and silent defaults
// ═══════════════════════════════════════════════════════════════
@Value("${myapp.api.key:default-key}")   // a "default" secret hides misconfiguration
private String apiKey;
// Failing at startup when a required property is missing is a FEATURE.
// Prefer validated, typed configuration:
@ConfigurationProperties("myapp.api")
@Validated
public record ApiProperties(@NotBlank String key, @DefaultValue("5s") Duration timeout) {}

// ═══════════════════════════════════════════════════════════════
// PITFALL 3: @Async and transactions
// ═══════════════════════════════════════════════════════════════
@Service
public class OrderService {
    @Transactional
    public void placeOrder(Order order) {
        orderRepository.save(order);
        notifier.sendConfirmation(order.getId());   // @Async method on another bean
        // The async method runs on another thread, OUTSIDE this transaction. It may
        // run BEFORE this transaction commits, so it may not see the new order,
        // and it still runs if this transaction later rolls back.
    }
}
// Fix: publish an event and handle it after commit:
//   applicationEventPublisher.publishEvent(new OrderPlaced(order.getId()));
//   @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT) @Async
//   void on(OrderPlaced e) { ... }
// (@Async + @Transactional on the SAME method does work: it starts a new
//  transaction on the async thread. What never happens is the CALLER's
//  transaction propagating across threads.)
// Also configure the async executor: by default Boot's applicationTaskExecutor
// (ThreadPoolTaskExecutor, or virtual threads when enabled) is used.

// ═══════════════════════════════════════════════════════════════
// PITFALL 4: Open Session In View (on by default)
// ═══════════════════════════════════════════════════════════════
// spring.jpa.open-in-view=true (default) keeps the EntityManager open for the whole
// request so lazy loading "works" in controllers and serializers:
// - N+1 queries hide outside the service layer
// - a connection can be held while the response renders
// Fix: spring.jpa.open-in-view=false and fetch what each use case needs.

// ═══════════════════════════════════════════════════════════════
// PITFALL 5: @Cacheable on self-invocation
// ═══════════════════════════════════════════════════════════════
@Service
public class ProductService {
    @Cacheable("products")
    public Product getProduct(Long id) {
        return productRepository.findById(id).orElseThrow();
    }

    public Product getProductWithDiscount(Long id) {
        Product product = getProduct(id);   // this.getProduct(): proxy bypassed, no cache
        return applyDiscount(product);
    }
}
// Fix: call it through another bean (or the proxy), or use the CacheManager directly.
// Also: configure a real cache (Caffeine with size + TTL); the default
// ConcurrentMapCacheManager never evicts.

// ═══════════════════════════════════════════════════════════════
// PITFALL 6: Virtual threads turned on without limits
// ═══════════════════════════════════════════════════════════════
// spring.threads.virtual.enabled=true (Java 21+) removes Tomcat's 200-thread cap.
// The bottleneck moves to the connection pool and downstream services: size
// Hikari deliberately, set timeouts everywhere, and add concurrency limits
// (Framework 7's @ConcurrencyLimit, a Semaphore, or a bulkhead) for fragile
// dependencies. Use Java 24+ (JEP 491) to avoid pinning in synchronized code of
// older libraries, or check JFR jdk.VirtualThreadPinned on Java 21.

// ═══════════════════════════════════════════════════════════════
// PITFALL 7: HTTP clients without timeouts
// ═══════════════════════════════════════════════════════════════
// Configure connect/read timeouts on every RestClient/WebClient/HTTP interface
// client (spring.http.client.* properties / ClientHttpRequestFactorySettings).
// A slow dependency without timeouts exhausts threads or connections and takes
// the whole service down. Use RestClient for new blocking code; RestTemplate is
// in maintenance and slated for deprecation in Framework 7.1.
```

### Native Images and Startup

```java
// GraalVM native image (Boot 3.0+, GraalVM 25+ for Boot 4):
//   ./mvnw -Pnative native:compile      or     ./gradlew nativeCompile
//   or build a container: ./mvnw -Pnative spring-boot:build-image
// Spring AOT runs at build time: evaluates conditions, generates bean definitions
// as code, and emits reachability metadata (reflection, proxies, resources).
// + startup in tens of milliseconds, low memory: good for scale-to-zero and CLIs
// - long builds, no JIT (lower peak throughput unless using PGO), closed world:
//   classpath fixed at build time, @Profile/@ConditionalOnProperty decisions that
//   change bean STRUCTURE can't flip at runtime, reflection needs hints
//   (RuntimeHintsRegistrar, @RegisterReflectionForBinding)
//
// Staying on the JVM but starting faster:
// - CDS (Boot 3.3+ documents the training-run workflow)
// - JDK AOT cache (Java 24+; JEP 483/514/515): java -XX:AOTCacheOutput=app.aot ...
// - Spring AOT on the JVM: -Dspring.aot.enabled=true with AOT-processed classes
// - spring.main.lazy-initialization=true (startup only; shifts cost and errors to
//   the first request)
```

---

## 12. Spring Boot Interview Questions

### Beginner

<details>
<summary><b>Q1: What is Dependency Injection? Why does Spring prefer constructor injection?</b></summary>

**Answer:** Dependency Injection means an object receives its collaborators from outside instead of creating or looking them up itself, so the container (or a test) decides which implementations to use. Spring recommends constructor injection because:
1. **Immutability**: dependencies can be `final`
2. **Testability**: `new Service(mockA, mockB)` with no container or reflection
3. **Completeness**: the object can't exist without its required dependencies; missing beans fail at startup
4. **Cycles fail fast**: a constructor cycle can't be resolved, so it's reported at startup instead of producing half-initialized beans
5. **Visibility**: a long constructor makes "this class does too much" obvious
</details>

<details>
<summary><b>Q2: What is the difference between @Component, @Service, @Repository, and @Controller?</b></summary>

**Answer:** All are `@Component` specializations, picked up by component scanning:
- **@Component**: generic Spring-managed bean
- **@Service**: business/service layer; no extra behaviour, it documents intent (and can be targeted by pointcuts)
- **@Repository**: data access layer; enables **exception translation** (via `PersistenceExceptionTranslationPostProcessor`) from technology-specific exceptions to Spring's `DataAccessException` hierarchy. Spring Data repository interfaces get this without the annotation.
- **@Controller**: web layer; detected by `RequestMappingHandlerMapping` as a handler. `@RestController` = `@Controller` + `@ResponseBody`.
</details>

<details>
<summary><b>Q3: What is Spring Boot auto-configuration?</b></summary>

**Answer:** Auto-configuration registers beans based on:
1. **Classpath**: e.g. a JDBC driver and HikariCP present → configure a `DataSource`
2. **Existing beans**: if you defined a `DataSource`, Boot backs off (`@ConditionalOnMissingBean`)
3. **Properties**: `spring.datasource.*` customize it
4. **Conditions**: `@ConditionalOnClass`, `@ConditionalOnProperty`, etc.

Candidates are listed in `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` files, processed after user configuration, filtered by conditions. Exclude with `@SpringBootApplication(exclude = ...)` or `spring.autoconfigure.exclude`; inspect with `--debug` or `/actuator/conditions`.
</details>

### Intermediate

<details>
<summary><b>Q4: How does Spring resolve circular dependencies?</b></summary>

**Answer:** First: **Spring Boot forbids circular references by default since 2.6** (`spring.main.allow-circular-references=false`); the startup failure lists the cycle. The mechanism below applies when they're allowed (plain Spring Framework, or that property set to `true`).

`DefaultSingletonBeanRegistry` keeps three maps:
1. **`singletonFactories`** (level 3): right after a singleton is instantiated (before population), an `ObjectFactory` for it is registered.
2. **`earlySingletonObjects`** (level 2): when another bean needs it while it's still being created, the factory is called. It calls `getEarlyBeanReference()`, which lets the auto-proxy creator return an **early proxy** if the bean needs one, and the result is cached here.
3. **`singletonObjects`** (level 1): fully initialized beans.

**Limitations:** constructor-injection cycles can't be resolved (no reference exists before a constructor returns); prototype-scoped cycles aren't supported; and if a post-processor wraps the bean differently *after* the early reference was handed out (e.g. `@Async`), Spring fails with `BeanCurrentlyInCreationException`.

**Fix the design** rather than enabling cycles: extract shared logic into a third bean, use events, or inject lazily (`@Lazy`, `ObjectProvider`).
</details>

<details>
<summary><b>Q5: What is the difference between JDK Dynamic Proxy and CGLIB Proxy?</b></summary>

**Answer:**
- **JDK proxy**: `java.lang.reflect.Proxy` implementing the bean's interfaces; only interface methods are advised and the bean can only be injected by interface type. Plain Spring's default when the bean implements an interface.
- **CGLIB proxy**: a runtime-generated **subclass** (Spring's repackaged CGLIB in `spring-core`); advises public/protected/package-visible non-final methods; can't proxy final classes or methods. **Spring Boot's default** (`spring.aop.proxy-target-class=true`).

Performance differences between them are negligible for application code. The practical differences are injection by concrete type, `final` methods silently not being advised, and (for both) self-invocation bypassing the proxy. Framework 7's `@Proxyable` lets you choose per bean.
</details>

<details>
<summary><b>Q6: How does @Transactional work with AOP?</b></summary>

**Answer:**
1. `@EnableTransactionManagement` (auto-configured by Boot) registers `BeanFactoryTransactionAttributeSourceAdvisor` (pointcut: methods/classes with `@Transactional`; advice: `TransactionInterceptor`).
2. An **auto-proxy creator** (a `BeanPostProcessor`) wraps matching beans in a proxy after initialization.
3. On a call through the proxy, `TransactionInterceptor`:
   - reads the attributes (propagation, isolation, timeout, readOnly, rollback rules)
   - asks the `PlatformTransactionManager` to begin, join, suspend or create a savepoint
   - invokes the method (`invocation.proceed()`)
   - commits on normal return; rolls back on `RuntimeException`/`Error` (or configured rules), otherwise commits
4. Resources and state are bound to the current thread by `TransactionSynchronizationManager`.

**Critical:** only calls through the proxy are transactional (self-invocation isn't), private methods never are, and the transaction doesn't cross threads. Reactive code uses `ReactiveTransactionManager` with the Reactor context instead of thread-locals.
</details>

### Advanced

<details>
<summary><b>Q7: What happens on Spring Boot startup when `@SpringBootApplication` is encountered?</b></summary>

**Answer:** `SpringApplication.run()`:
1. **Create `SpringApplication`**: deduce the web application type (servlet, reactive, none), load `BootstrapRegistryInitializer`s, `ApplicationContextInitializer`s and `ApplicationListener`s from `META-INF/spring.factories`.
2. **Starting**: `ApplicationStartingEvent`.
3. **Prepare the `Environment`**: property sources (command line, env vars, `application.properties`/`.yml`, profiles, config data imports), `EnvironmentPostProcessor`s; `ApplicationEnvironmentPreparedEvent`.
4. **Banner** (optional).
5. **Create the context**: a `ServletWebServerApplicationContext` variant for servlet apps (reactive equivalent for WebFlux).
6. **Prepare the context**: apply initializers, register the main class as a bean source; `ApplicationContextInitializedEvent`, then `ApplicationPreparedEvent`.
7. **Refresh** (`AbstractApplicationContext.refresh()`): parse configuration (component scan, auto-configuration), register post-processors, `onRefresh()` **creates the embedded web server**, instantiate singletons, `finishRefresh()` starts `SmartLifecycle` beans (the web server starts accepting requests) and publishes `ContextRefreshedEvent`.
8. **Started**: `ApplicationStartedEvent`, liveness = CORRECT.
9. **Runners**: `ApplicationRunner` and `CommandLineRunner` beans execute.
10. **Ready**: `ApplicationReadyEvent`, readiness = ACCEPTING_TRAFFIC.

If anything fails, `ApplicationFailedEvent` is published and `FailureAnalyzer`s print a readable explanation.
</details>

<details>
<summary><b>Q8: Design a multi-tenant SaaS application with Spring Boot. How do you isolate tenant data?</b></summary>

**Answer:** Resolve the tenant once per request (subdomain, header, or a JWT claim), store it in a request-scoped context (a `ScopedValue` on Java 25, or a `ThreadLocal` cleared in `finally`), and choose an isolation model:

1. **Database per tenant**: strongest isolation, per-tenant backup/restore and scaling, noisy neighbours contained. Cost: many connection pools and databases to migrate. Route with `AbstractRoutingDataSource`:
```java
public class TenantRoutingDataSource extends AbstractRoutingDataSource {
    @Override
    protected Object determineCurrentLookupKey() {
        return TenantContext.current();   // key into the map of per-tenant DataSources
    }
}
```

2. **Schema per tenant**: one database, a schema per tenant. Use Hibernate's multi-tenancy (`MultiTenantConnectionProvider` + `CurrentTenantIdentifierResolver`) to set the schema on a shared pool's connections (`SET search_path` in PostgreSQL). Migrations run per schema (Flyway/Liquibase per tenant), which gets slow with thousands of tenants.

3. **Shared tables with a `tenant_id` column**: cheapest and simplest to operate at scale; weakest isolation (one missing filter leaks data). Enforce it in more than one place:
```java
@Entity
public class Order {
    @TenantId                 // Hibernate 6+: set on insert and added to every query
    private String tenantId;
}
// plus database-level enforcement, e.g. PostgreSQL Row-Level Security policies
// keyed on a session variable set per transaction
```
(`@Where` can't take parameters and is deprecated in favour of `@SQLRestriction`; for dynamic filters use `@TenantId` or `@Filter`.)

Many SaaS products mix them: shared tables for the long tail of small tenants, dedicated databases for large or regulated ones. Whatever you choose, include the tenant in cache keys, metrics/log context and async messages, and test cross-tenant access explicitly.
</details>

<details>
<summary><b>Q9: How would you optimize a Spring Boot application that's too slow to start?</b></summary>

**Answer:** Measure first: `/actuator/startup` (with `BufferingApplicationStartup`) or JFR shows which beans and steps are slow. Then:
1. **Remove work**: unused starters and auto-configurations (fewer beans, fewer conditions), narrow component scanning, no eager network calls or cache warming in `@PostConstruct` (move them to `ApplicationReadyEvent` or make them async).
2. **Background initialization** of slow, independent beans: Framework 6.2+ `@Bean(bootstrap = Bean.Bootstrap.BACKGROUND)` with a bootstrap executor.
3. **Lazy initialization**: `spring.main.lazy-initialization=true` speeds startup but moves cost and configuration errors to the first request; acceptable in dev, risky in prod.
4. **JVM-level**: CDS (Boot 3.3+) or the JDK AOT cache (Java 24+) cut class-loading time without code changes; Spring AOT on the JVM precomputes bean definitions.
5. **GraalVM native image** when startup and memory matter most (serverless, scale to zero), accepting longer builds and closed-world constraints.
6. **Don't rely on** `spring-context-indexer`: it's deprecated since Framework 6.1.

Also check for slow `BeanPostProcessor`s, Hibernate schema validation/DDL on startup, and Flyway migrations running at boot.
</details>

<details>
<summary><b>Q10: Design a rate-limiting system for a Spring Boot REST API. Could you implement it as a custom filter or interceptor?</b></summary>

**Answer:** Decide *where* first. A gateway or service mesh (or a CDN/WAF) is usually the right place for coarse per-client limits. In the app, use a **servlet filter** if you need to reject requests before authentication, deserialization or any MVC work, or a **`HandlerInterceptor`** if limits depend on the resolved handler or the authenticated user (it runs after Spring Security's filters). The limiter state must be **shared across instances** (Redis), and the check must be **atomic**.

```java
@Component
public class RateLimitingInterceptor implements HandlerInterceptor {
    private final RateLimiter rateLimiter;   // e.g. Bucket4j with a Redis backend

    public RateLimitingInterceptor(RateLimiter rateLimiter) {
        this.rateLimiter = rateLimiter;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response,
                             Object handler) throws Exception {
        String key = clientKey(request) + ":" + request.getMethod() + ":" + routeOf(request);
        RateLimitResult result = rateLimiter.tryConsume(key);
        response.setHeader("RateLimit-Remaining", String.valueOf(result.remaining()));
        if (!result.allowed()) {
            response.setStatus(429);
            response.setHeader("Retry-After", String.valueOf(result.retryAfterSeconds()));
            response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
            response.getWriter().write("""
                {"title": "Too Many Requests", "status": 429}
                """);
            return false;
        }
        return true;
    }

    private String clientKey(HttpServletRequest request) {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.isAuthenticated() && !(auth instanceof AnonymousAuthenticationToken)) {
            return "user:" + auth.getName();
        }
        // Behind a load balancer use the forwarded client IP (server.forward-headers-strategy),
        // and only trust X-Forwarded-For from your own proxies.
        return "ip:" + request.getRemoteAddr();
    }

    private String routeOf(HttpServletRequest request) {
        // Use the matched pattern (/orders/{id}), not the raw URI, or every id gets its own bucket
        Object pattern = request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE);
        return pattern != null ? pattern.toString() : request.getRequestURI();
    }
}

@Configuration
public class WebConfig implements WebMvcConfigurer {
    private final RateLimitingInterceptor rateLimitingInterceptor;

    public WebConfig(RateLimitingInterceptor rateLimitingInterceptor) {
        this.rateLimitingInterceptor = rateLimitingInterceptor;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(rateLimitingInterceptor)
            .addPathPatterns("/api/**")
            .excludePathPatterns("/api/public/**");
    }
}
```

**The limiter itself.** A sliding-window log in a Redis sorted set works, but the remove/count/add sequence must run **atomically** (a Lua script or `MULTI`), and each member must be unique (two requests in the same millisecond would otherwise collapse into one entry):

```lua
-- KEYS[1] = bucket key; ARGV = now_ms, window_ms, limit, unique_request_id
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1] - ARGV[2])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return 1
```

Trade-offs: the sliding log is exact but stores one entry per request (memory grows with the limit); a **token bucket** (Bucket4j, or a small Lua script storing tokens + last refill time) uses O(1) memory per key and allows controlled bursts; a fixed window counter (`INCR` + `EXPIRE`) is cheapest but allows 2x bursts at window edges. Decide what happens when Redis is unavailable (fail open for availability, or closed for protection), and expose the limits in headers (`RateLimit-*`, `Retry-After`).
</details>

---

## Quick Reference: Spring Boot at a Glance

| Concept | Key Point |
|---------|-----------|
| **Versions (Oct 2026)** | Boot 4.1 / 4.0 on Framework 7.0; Java 17+ (25 recommended); Jakarta EE 11; Boot 3.5 OSS support ended June 2026 |
| **IoC container** | Bean definitions → BFPPs → BPPs → eager singletons at `refresh()` |
| **Bean lifecycle** | instantiate → populate → aware → BPP before (incl. `@PostConstruct`) → init → BPP after (proxies) → ready → destroy |
| **Auto-configuration** | `AutoConfiguration.imports` + conditions, processed after user config; `--debug` to see why |
| **AOP proxy** | CGLIB by default in Boot; JDK proxies in plain Spring for interface beans; self-invocation bypasses both |
| **@Transactional** | Thread-bound; default REQUIRED; rollback on unchecked exceptions; REQUIRES_NEW = second connection |
| **Circular dependencies** | Forbidden by default since Boot 2.6; redesign instead of re-enabling |
| **OSIV** | On by default; turn it off and fetch explicitly |
| **Security** | `FilterChainProxy` → `SecurityFilterChain`; `AuthorizationFilter` + `AuthorizationManager`; lambda DSL only in Security 7 |
| **HTTP clients** | `RestClient`, HTTP interface clients (`@HttpExchange`, `@ImportHttpServices`); `RestTemplate` heading for deprecation |
| **Observability** | Micrometer Observation → metrics + traces; OTLP via `spring-boot-starter-opentelemetry` (Boot 4); structured logging (3.4+) |
| **Virtual threads** | `spring.threads.virtual.enabled=true`; add explicit concurrency limits |
| **Testing** | Unit tests + slices + Testcontainers with `@ServiceConnection`; `@MockitoBean` replaces `@MockBean` |
| **Startup** | CDS / JDK AOT cache on the JVM; GraalVM native image for the fastest start |

---

> *Staff/Principal interviews focus on WHY Spring works the way it does: proxies, transaction boundaries, auto-configuration, and how those choices fail in production.*
