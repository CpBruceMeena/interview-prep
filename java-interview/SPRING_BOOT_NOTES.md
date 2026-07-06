# ☕ Spring Boot Internals — Principal Engineer Deep-Dive

> **A comprehensive reference on Spring Boot, DI container, AOP, transactions, security, and production patterns**
> *Designed for Staff/Principal Engineer interviews (10+ years experience)*

---

## Table of Contents

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

---

## 1. IoC Container & Dependency Injection

### Container Hierarchy

```
BeanFactory (interface)
  └── The root container interface
  └── Lazy initialization by default
  └── getBean(), containsBean(), isSingleton()

ApplicationContext (interface extends BeanFactory)
  └── Eager initialization (pre-instantiate singletons)
  └── Event publication (ApplicationEventPublisher)
  └── Resource loading (ResourceLoader)
  └── Message i18n (MessageSource)
  └── Environment abstraction (Environment)

ConfigurableApplicationContext (interface)
  └── refresh(), close(), registerShutdownHook()

AbstractApplicationContext
  └── Template method pattern for refresh()
  └── Implements all ApplicationContext contracts
  
AnnotationConfigApplicationContext
  └── Java-based configuration (@Configuration, @ComponentScan)
  
AnnotationConfigServletWebServerApplicationContext
  └── Spring Boot's default context (embedded Tomcat + annotation config)
```

### The `refresh()` Method — 13 Steps

```java
// AbstractApplicationContext.refresh() — the heart of Spring:
@Override
public void refresh() throws BeansException, IllegalStateException {
    synchronized (this.startupShutdownMonitor) {
        // 1. Prepare refresh: set startup date, active flags
        prepareRefresh();
        
        // 2. Obtain fresh bean factory: read configuration → BeanDefinition
        ConfigurableListableBeanFactory beanFactory = obtainFreshBeanFactory();
        
        // 3. Prepare bean factory: set classloader, post-processors
        prepareBeanFactory(beanFactory);
        
        // 4. Post-process bean factory: ALLOW SUBCLASSES to modify
        postProcessBeanFactory(beanFactory);
        
        // 5. Invoke BeanFactoryPostProcessors (@PropertySource, @ComponentScan)
        invokeBeanFactoryPostProcessors(beanFactory);
        
        // 6. Register BeanPostProcessors (@Autowired, @Resource, etc.)
        registerBeanPostProcessors(beanFactory);
        
        // 7. Initialize message source (i18n)
        initMessageSource();
        
        // 8. Initialize event multicaster
        initApplicationEventMulticaster();
        
        // 9. Refresh other contexts (ONLY in subclasses — web containers)
        onRefresh();
        
        // 10. Register listeners for ApplicationEvents
        registerListeners();
        
        // 11. Instantiate ALL non-lazy singleton beans
        finishBeanFactoryInitialization(beanFactory);
        
        // 12. Last step: publish Lifecycle events, start lifecycle beans
        finishRefresh();
    }
}
```

### Bean Scopes

| Scope | Description | Use Case |
|-------|-------------|----------|
| **singleton** | One instance per container (default) | Stateless services, DAOs |
| **prototype** | New instance per injection/getBean | Stateful objects |
| **request** | One instance per HTTP request | Request-scoped data |
| **session** | One instance per HTTP session | User session data |
| **application** | One instance per ServletContext | Application-wide shared state |
| **websocket** | One instance per WebSocket session | WebSocket data |

### Injection Types

```java
// ═══════════════════════════════════════════════════════════════
// 1. Constructor Injection (PREFERRED — Spring team recommendation)
// ═══════════════════════════════════════════════════════════════
@Service
public class UserService {
    private final UserRepository userRepository;
    private final EmailService emailService;
    
    // Constructor injection:
    // ✅ Final fields (immutability)
    // ✅ Easy testing (no reflection for construction)
    // ✅ No circular dependency issues
    // ✅ Explicit dependencies
    public UserService(UserRepository userRepository, EmailService emailService) {
        this.userRepository = userRepository;
        this.emailService = emailService;
    }
}

// ═══════════════════════════════════════════════════════════════
// 2. Setter Injection
// ═══════════════════════════════════════════════════════════════
@Service
public class UserService {
    private UserRepository userRepository;
    
    @Autowired
    public void setUserRepository(UserRepository userRepository) {
        this.userRepository = userRepository;
    }
    // ⚠️ Can't be final
    // ⚠️ Circular dependency SUPPORTED (level 3 caching)
}

// ═══════════════════════════════════════════════════════════════
// 3. Field Injection (NOT RECOMMENDED)
// ═══════════════════════════════════════════════════════════════
@Service
public class UserService {
    @Autowired
    private UserRepository userRepository;
    // ❌ Can't be final
    // ❌ Hidden dependencies
    // ❌ Testing requires reflection (Mockito.mock())
    // ❌ Circular dependency debugging harder
}

// ═══════════════════════════════════════════════════════════════
// 4. Java Config Injection
// ═══════════════════════════════════════════════════════════════
@Configuration
public class AppConfig {
    @Bean
    public UserService userService(UserRepository userRepository,
                                     EmailService emailService) {
        return new UserService(userRepository, emailService);
        // Constructor injection in @Bean method
    }
}
```

---

## 2. Bean Lifecycle & Post-Processors

### Complete Bean Lifecycle (11 Steps)

```java
// Step 1: Instantiate — create raw bean via constructor (reflection)
// Step 2: Populate — inject dependencies (field/setter injection)
// Step 3: Set bean name — if BeanNameAware
// Step 4: Set bean factory — if BeanFactoryAware
// Step 5: Set application context — if ApplicationContextAware
// Step 6: Pre-init — BeanPostProcessor.postProcessBeforeInitialization
// Step 7: @PostConstruct — init method
// Step 8: afterPropertiesSet — if InitializingBean
// Step 9: Custom init-method (@Bean(initMethod = "init"))
// Step 10: Post-init — BeanPostProcessor.postProcessAfterInitialization
//         → PROXY CREATION happens HERE (AOP, @Transactional, @Cacheable)
//         → The returned proxy REPLACES the bean in the container
// Step 11: Bean is ready for use
// ...
// Step 12: @PreDestroy — destroy method
// Step 13: destroy() — if DisposableBean
// Step 14: Custom destroy-method (@Bean(destroyMethod = "cleanup"))
```

### BeanPostProcessor — The Most Powerful Extension Point

```java
@Component
public class CustomBeanPostProcessor implements BeanPostProcessor {
    
    @Override
    public Object postProcessBeforeInitialization(Object bean, String beanName) 
            throws BeansException {
        // Called BEFORE @PostConstruct
        // Can inspect and wrap the bean
        if (bean instanceof SomeService) {
            log.info("Before init: {}", beanName);
        }
        return bean;  // Must return the bean (or a replacement!)
    }
    
    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) 
            throws BeansException {
        // Called AFTER @PostConstruct
        // THIS is where AOP proxies are created!
        // AnnotationAwareAspectJAutoProxyCreator.postProcessAfterInitialization()
        // scans for @Transactional, @Cacheable, @Async, etc.
        // and creates the proxy if needed
        
        if (bean instanceof MonitoredService) {
            // Create a JDK proxy
            return Proxy.newProxyInstance(
                bean.getClass().getClassLoader(),
                bean.getClass().getInterfaces(),
                (proxy, method, args) -> {
                    long start = System.nanoTime();
                    Object result = method.invoke(bean, args);
                    long duration = System.nanoTime() - start;
                    log.info("{} took {}μs", method.getName(), duration / 1000);
                    return result;
                });
        }
        return bean;
    }
}
```

### BeanFactoryPostProcessor — Modify Bean Definitions Before Creation

```java
@Component
public static class CustomBeanFactoryPostProcessor 
        implements BeanFactoryPostProcessor {
    
    @Override
    public void postProcessBeanFactory(ConfigurableListableBeanFactory factory) 
            throws BeansException {
        // Modify bean definitions BEFORE any beans are created
        // (Step 5 of refresh())
        
        BeanDefinition bd = factory.getBeanDefinition("dataSource");
        MutablePropertyValues pv = bd.getPropertyValues();
        
        // Override URL based on environment
        String url = determineUrl();
        pv.add("url", url);
        
        // Change scope
        bd.setScope("singleton");
        
        // Add property to all beans of a certain type
        String[] beanNames = factory.getBeanNamesForType(DataSource.class);
        for (String name : beanNames) {
            factory.getBeanDefinition(name).setLazyInit(false);
        }
    }
}
```

### BeanDefinitionRegistryPostProcessor — Register New Bean Definitions

```java
@Component
public static class CustomBeanDefinitionRegistryPostProcessor 
        implements BeanDefinitionRegistryPostProcessor {
    
    @Override
    public void postProcessBeanDefinitionRegistry(BeanDefinitionRegistry registry) 
            throws BeansException {
        // Register ADDITIONAL bean definitions programmatically
        // This is how @Configuration classes, @ComponentScan, @Import work
        
        // Register a new bean definition
        GenericBeanDefinition bd = new GenericBeanDefinition();
        bd.setBeanClass(MyService.class);
        bd.getPropertyValues().add("timeout", 5000);
        registry.registerBeanDefinition("myService", bd);
    }
    
    @Override
    public void postProcessBeanFactory(ConfigurableListableBeanFactory factory) {
        // Also implements BeanFactoryPostProcessor
    }
}
```

---

## 3. Auto-Configuration & Conditionals

### How Spring Boot Auto-Configuration Works

```java
// 1. @SpringBootApplication ≡ @EnableAutoConfiguration + @ComponentScan + @Configuration

// 2. @EnableAutoConfiguration imports AutoConfigurationImportSelector
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Import(AutoConfigurationImportSelector.class)
public @interface EnableAutoConfiguration {}

// 3. AutoConfigurationImportSelector reads:
//    META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
//    (Spring Boot 3.x format)
//
//    Spring Boot 2.x format: META-INF/spring.factories
//    Key: org.springframework.boot.autoconfigure.EnableAutoConfiguration

// 4. Sample content of AutoConfiguration.imports:
// org.springframework.boot.autoconfigure.web.servlet.WebMvcAutoConfiguration
// org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration
// org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration
// org.springframework.boot.autoconfigure.orm.jpa.HibernateJpaAutoConfiguration
// ... 100+ auto-configuration classes

// 5. Each auto-configuration class:
@AutoConfiguration(after = {DataSourceAutoConfiguration.class})
@ConditionalOnClass(DataSource.class)
@EnableConfigurationProperties(DataSourceProperties.class)
@ConditionalOnMissingBean(DataSource.class)
public class JdbcTemplateAutoConfiguration {
    
    @Bean
    @ConditionalOnMissingBean(JdbcOperations.class)
    public JdbcTemplate jdbcTemplate(DataSource dataSource) {
        return new JdbcTemplate(dataSource);
    }
}
```

### @Conditional Mechanism

```java
// ALL @Conditional annotations use the Condition SPI:

@FunctionalInterface
public interface Condition {
    boolean matches(ConditionContext context, AnnotatedTypeMetadata metadata);
}

// ConditionContext provides:
// Registry (BeanDefinitionRegistry) — check bean definitions
// BeanFactory (ConfigurableListableBeanFactory) — check actual beans
// Environment — check properties, profiles
// ResourceLoader — check resources
// ClassLoader — check classpath

// @ConditionalOnClass:
// Checks if specified classes are on the classpath
// Uses ClassUtils.isPresent() — does NOT load the class

// @ConditionalOnMissingBean:
// Checks if bean does NOT already exist
// Ensures user-defined beans take precedence
// Only checks BeanDefinition, NOT actual bean instances initially

// @ConditionalOnProperty:
@Retention(RetentionPolicy.RUNTIME)
@Conditional(OnPropertyCondition.class)
public @interface ConditionalOnProperty {
    String prefix() default "";
    String name();          // Property name
    String havingValue() default "";  // Required value
    boolean matchIfMissing() default false;  // Default behavior if property missing
}

// Example:
@ConditionalOnProperty(name = "myapp.feature.flag", havingValue = "true")
@Bean
public FeaturedService featuredService() {
    return new FeaturedService();
}
```

### Auto-Configuration Ordering

```java
// Order is controlled by:
// 1. @AutoConfiguration(after = {...}, before = {...})
// 2. @AutoConfigureOrder (numeric order)
// 3. @AutoConfigureAfter / @AutoConfigureBefore (legacy)

// Typical execution order:
// DataSourceAutoConfiguration → JdbcTemplateAutoConfiguration
// → HibernateJpaAutoConfiguration → TransactionAutoConfiguration
// → WebMvcAutoConfiguration → SecurityAutoConfiguration
// → ... (100+ more)

// EXCLUDING auto-configuration:
@SpringBootApplication(exclude = {
    DataSourceAutoConfiguration.class,  // When not using a database
    SecurityAutoConfiguration.class     // Custom security setup
})
public class MyApplication {}
```

### Custom Auto-Configuration

```java
// 1. Create your auto-configuration class:
@AutoConfiguration
@ConditionalOnClass(MyService.class)
@EnableConfigurationProperties(MyProperties.class)
public class MyAutoConfiguration {
    
    @Bean
    @ConditionalOnMissingBean
    public MyService myService(MyProperties properties) {
        return new MyService(properties.getUrl(), properties.getTimeout());
    }
    
    @Bean
    @ConditionalOnProperty(name = "myapp.monitoring.enabled", havingValue = "true")
    public MyMonitor myMonitor() {
        return new MyMonitor();
    }
}

// 2. Create properties class:
@ConfigurationProperties(prefix = "myapp")
public class MyProperties {
    private String url = "http://localhost:8080";
    private int timeout = 5000;
    // getters + setters...
}

// 3. Register in META-INF/spring/AutoConfiguration.imports:
//    com.mycompany.starter.MyAutoConfiguration

// 4. Add spring boot starter (for auto-config discovery):
//    In META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
```

---

## 4. AOP — Aspect-Oriented Programming

### How Spring AOP Works

```java
// Spring AOP is PROXY-BASED:
// 1. Only intercepts PUBLIC method calls on SPRING-MANAGED beans
// 2. The proxy intercepts the call → applies aspects → calls real method
// 3. Two proxy types: JDK Dynamic Proxy (interface) or CGLIB (subclass)
```

### Proxy Mechanisms

```java
// JDK Dynamic Proxy (DEFAULT when bean implements an interface):
// - Interface: java.lang.reflect.Proxy
// - Creates proxy implementing ALL bean interfaces
// - Proxy passes to InvocationHandler which chains interceptors
// - ONLY intercepts methods declared in interfaces

// CGLIB Proxy (used when bean does NOT implement interfaces):
// - Creates SUBCLASS of the target class
// - Overrides ALL non-final, non-static methods
// - Method interception via MethodInterceptor interface
// - REQUIRES CGLIB or Spring's own ByteBuddy variant

// When Spring chooses:
@EnableAspectJAutoProxy  // ← Enables CGLIB by default (Spring Boot auto-configures)
@EnableAspectJAutoProxy(proxyTargetClass = true)   // Force CGLIB
@EnableAspectJAutoProxy(proxyTargetClass = false)  // Force JDK proxy
```

### The Self-Invocation Problem

```java
@Service
public class UserService {
    
    @Transactional
    public void createUser(User user) {
        save(user);
        sendWelcomeEmail(user.getEmail());  // ← NOT TRANSACTIONAL!
    }
    
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void sendWelcomeEmail(String email) {
        // Runs WITHOUT a transaction!
        // Because: this.createUser() called the proxy
        //          But this.sendWelcomeEmail() calls the RAW bean (not proxy)
    }
}

// Why?
// - userService bean = PROXY wrapping real UserService
// - userService.createUser(...) → proxy → open tx → real method
// - Inside createUser(): "this" = REAL UserService, NOT the proxy
// - So "this".sendWelcomeEmail() has NO transactional behavior!

// FIX 1: Self-inject the proxy (Spring 4+)
@Service
public class UserService {
    @Autowired
    private UserService self;  // ← Injects the PROXY (not the real bean!)
    
    @Transactional
    public void createUser(User user) {
        save(user);
        self.sendWelcomeEmail(user.getEmail());  // ← Goes through proxy!
    }
}

// FIX 2: Extract method to a separate @Service (cleanest)
// FIX 3: Use AspectJ compile-time weaving (no proxy, direct bytecode modification)
// FIX 4: Use TransactionTemplate programmatically

@Service
public class UserService {
    @Autowired
    private TransactionTemplate txTemplate;
    
    public void createUser(User user) {
        txTemplate.execute(status -> {
            save(user);
            txTemplate.execute(status2 -> {  // REQUIRES_NEW equivalent
                sendEmail(user.getEmail());
                return null;
            });
            return null;
        });
    }
}
```

### AspectJ Pointcut Expressions

```java
// EXECUTION — most common
@Pointcut("execution(public * com.myapp.service.*.*(..))")
// Match: all public methods in com.myapp.service package

// WITHIN — match all methods in a class/package
@Pointcut("within(com.myapp.service..*)")
// Match: all methods in any class under service package

// ANNOTATION — match annotated methods
@Pointcut("@annotation(org.springframework.transaction.annotation.Transactional)")
// Match: methods with @Transactional

// BEAN — match specific bean name
@Pointcut("bean(*Service)")
// Match: all beans ending with "Service"

// COMBINING:
@Around("execution(* com.myapp.service.*.*(..)) && @annotation(tx)")
public Object aroundTransactional(ProceedingJoinPoint pjp, 
                                    Transactional tx) throws Throwable {
    // 'tx' parameter is the @Transactional annotation on the method
    return pjp.proceed();
}
```

### Creating a Custom Aspect

```java
@Aspect
@Component
public class LoggingAspect {
    private static final Logger log = LoggerFactory.getLogger(LoggingAspect.class);
    
    // Pointcut for all service methods
    @Pointcut("execution(public * com.myapp.service.*.*(..))")
    public void serviceMethods() {}
    
    // Around advice — wrap method execution
    @Around("serviceMethods()")
    public Object logExecutionTime(ProceedingJoinPoint joinPoint) throws Throwable {
        String methodName = joinPoint.getSignature().toShortString();
        Object[] args = joinPoint.getArgs();
        
        log.info("→ {} with args: {}", methodName, args);
        
        long start = System.nanoTime();
        try {
            Object result = joinPoint.proceed();  // Invoke real method
            long duration = (System.nanoTime() - start) / 1000;
            log.info("← {} returned in {}μs", methodName, duration);
            return result;
        } catch (Exception e) {
            log.error("✗ {} threw: {}", methodName, e.getMessage());
            throw e;
        }
    }
    
    // AfterThrowing advice
    @AfterThrowing(pointcut = "serviceMethods()", throwing = "ex")
    public void logException(JoinPoint joinPoint, Exception ex) {
        log.error("Exception in {}: {}", 
            joinPoint.getSignature().toShortString(), ex.toString());
    }
    
    // AfterReturning advice
    @AfterReturning(pointcut = "serviceMethods()", returning = "result")
    public void logReturn(JoinPoint joinPoint, Object result) {
        log.debug("{} returned: {}", joinPoint.getSignature().toShortString(), result);
    }
}
```

---

## 5. @Transactional — Propagation & Isolation

### Propagation Levels

```java
// The TransactionInterceptor creates the right transaction strategy:

// REQUIRED (default)
@Transactional(propagation = Propagation.REQUIRED)
public void method() {
    // 1. If no transaction → create new one
    // 2. If transaction exists → join it
}

// REQUIRES_NEW
@Transactional(propagation = Propagation.REQUIRES_NEW)
public void method() {
    // 1. If no transaction → create new one
    // 2. If transaction exists → SUSPEND it, create new, commit new, resume old
    // REQUIRES A NEW JDBC CONNECTION!
}

// NESTED
@Transactional(propagation = Propagation.NESTED)
public void method() {
    // 1. If no transaction → create new one (same as REQUIRED)
    // 2. If transaction exists → create SAVEPOINT, rollback to savepoint on failure
    // Uses JDBC Savepoints (3.0 feature)
}

// MANDATORY
@Transactional(propagation = Propagation.MANDATORY)
public void method() {
    // 1. Must have existing transaction → throws if none
}

// NEVER
@Transactional(propagation = Propagation.NEVER)
public void method() {
    // 1. Must NOT have existing transaction → throws if exists
}

// NOT_SUPPORTED
@Transactional(propagation = Propagation.NOT_SUPPORTED)
public void method() {
    // 1. If transaction exists → SUSPEND it
    // 2. Execute without transaction
    // 3. Resume original transaction
}

// SUPPORTS
@Transactional(propagation = Propagation.SUPPORTS)
public void method() {
    // 1. If transaction exists → join it
    // 2. If no transaction → execute without one
}
```

### Transaction Suspension Internals

```java
// When REQUIRES_NEW is encountered:
// 1. TransactionInterceptor detects existing transaction
// 2. Calls TransactionAspectSupport.suspend()
// 3. Inside suspend():
//    a. Get current connection from TransactionSynchronizationManager
//    b. Create SuspendedResourcesHolder
//    c. Unbind resources from ThreadLocal
//    d. Suspend synchronizations (transaction callbacks)
// 4. Starts new transaction:
//    a. Get NEW connection from datasource
//    b. Set autoCommit = false
//    c. Bind to ThreadLocal
// 5. Execute method body
// 6. Commit new transaction
// 7. Resume original:
//    a. Restore connection from SuspendedResourcesHolder
//    b. Rebind to ThreadLocal
//    c. Resume synchronizations

// IMPORTANT: Suspension requires TWO connections!
// If connection pool has max=10, and 10 threads are in REQUIRES_NEW:
//   - 10 connections for parent transactions (held, suspended)
//   - Each thread tries to get another connection for child
//   - Pool exhausted → DEADLOCK!
```

### Isolation Levels

```java
// DEFAULT → uses database default (usually READ_COMMITTED)
@Transactional(isolation = Isolation.DEFAULT)

// READ_UNCOMMITTED → dirty reads possible
@Transactional(isolation = Isolation.READ_UNCOMMITTED)

// READ_COMMITTED → no dirty reads (PostgreSQL default)
@Transactional(isolation = Isolation.READ_COMMITTED)
// - SELECT without lock (MVCC snapshot)
// - UPDATE/DELETE: row lock

// REPEATABLE_READ → no dirty/non-repeatable reads (MySQL default)
@Transactional(isolation = Isolation.REPEATABLE_READ)
// - PostgreSQL: snapshot from first query, may get serialization failure
// - MySQL: gap locks + next-key locks

// SERIALIZABLE → strongest isolation
@Transactional(isolation = Isolation.SERIALIZABLE)
// - All operations serialized
// - High contention → retry logic required
```

### Read-Only Optimization

```java
@Transactional(readOnly = true)
public List<User> findAllUsers() {
    // Hibernate optimizations:
    // - FlushMode = MANUAL (no dirty checking needed)
    // - No need to snapshot loaded entities
    // - No need to cascade persist/merge
    
    // JDBC optimization:
    // - connection.setReadOnly(true) → some databases optimize
    // - PostgreSQL: can route to read replicas
    
    return userRepository.findAll();
}

// readOnly = false (default)
@Transactional
public User saveUser(User user) {
    // Full flush mode, dirty checking, cascading
    return userRepository.save(user);
}
```

### Common Transaction Pitfalls

```java
// ═══════════════════════════════════════════════════════════════
// PITFALL 1: @Transactional on private methods
// ═══════════════════════════════════════════════════════════════
@Service
public class MyService {
    
    @Transactional  // ← DOES NOTHING!
    private void doWork() {
        // AOP proxy can't intercept private methods
        // CGLIB can't override private methods
    }
}

// ═══════════════════════════════════════════════════════════════
// PITFALL 2: @Transactional on non-public method in JDK proxy
// ═══════════════════════════════════════════════════════════════
@Service
public class MyService implements MyInterface {
    @Transactional  // ← DOES NOTHING if called via interface! (JDK proxy)
    public void doWork() {
        // JDK proxy only sees INTERFACE methods
        // Need CGLIB or proxyTargetClass = true
    }
}

// ═══════════════════════════════════════════════════════════════
// PITFALL 3: Transaction + checked exceptions
// ═══════════════════════════════════════════════════════════════
@Transactional
public void process() throws BusinessException {
    // DEFAULT: only rolls back on RuntimeException and Error
    // Checked exceptions do NOT trigger rollback!
    // To rollback on checked exceptions:
}
@Transactional(rollbackFor = BusinessException.class)
public void process() throws BusinessException {
    // Now rolls back on this checked exception too
}

// ═══════════════════════════════════════════════════════════════
// PITFALL 4: Transaction + try-catch
// ═══════════════════════════════════════════════════════════════
@Transactional
public void process() {
    try {
        someMethod();  // throws exception
    } catch (Exception e) {
        // Exception is CAUGHT — transaction will NOT rollback!
        // TransactionInterceptor sees "normal completion"
        // Mark for rollback: TransactionAspectSupport.currentTransactionStatus()
        //   .setRollbackOnly();
    }
}
```

---

## 6. Spring Data JPA & Hibernate

### Entity State Transitions

```
                 ┌──────────────────────┐
                 │     TRANSIENT         │
                 │  (new, not persisted) │
                 └──────────┬───────────┘
                            │ persist()
                            ▼
                 ┌──────────────────────┐
                 │     MANAGED          │ ← ─ ─ ─ ─ ─ ─ ─ ─
                 │  (attached to EM)    │                   │
                 └──────────┬───────────┘                   │
                            │                                │
               ┌────────────┼────────────┐                  │
               ▼            ▼            ▼                   │
        ┌──────────┐ ┌──────────┐ ┌──────────┐              │
        │ DETACHED │ │ REMOVED  │ │ MANAGED │              │
        │ (EM      │ │ (sched.  │ │ (re-     │              │
        │  closed) │ │  delete) │ │  attach) │              │
        └──────────┘ └──────────┘ └──────────┘              │
               │                              │              │
               └──────────────────────────────┘──────────────┘
                           merge()
```

### Fetch Strategies

```java
@Entity
public class Order {
    @Id
    private Long id;
    
    // LAZY (default for toMany)
    @OneToMany(mappedBy = "order", fetch = FetchType.LAZY)
    private List<OrderItem> items;
    
    // EAGER (default for toOne)
    @ManyToOne(fetch = FetchType.EAGER)
    private User user;
    
    // LAZY loading requires:
    // 1. Hibernate proxy (CGLIB or ByteBuddy)
    // 2. EntityManager still open
    // 3. OR explicit fetching via JPQL
}

// N+1 problem:
// List<Order> orders = orderRepository.findAll();
// for (Order order : orders) {
//     System.out.println(order.getItems().size());  // ← N additional queries!
// }

// FIX 1: JOIN FETCH
@Query("SELECT o FROM Order o JOIN FETCH o.items")
List<Order> findAllWithItems();

// FIX 2: @EntityGraph
@EntityGraph(attributePaths = {"items"})
@Query("SELECT o FROM Order o")
List<Order> findAllWithItems();

// FIX 3: batch fetching
@BatchSize(size = 50)  // Load 50 orders' items in one query
@Entity
public class Order { ... }
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
    
    // @Query — custom JPQL
    @Query("SELECT u FROM User u WHERE u.email = :email")
    Optional<User> findByEmailCustom(@Param("email") String email);
    
    // Native query
    @Query(value = "SELECT * FROM users u WHERE u.email = :email", 
           nativeQuery = true)
    Optional<User> findByEmailNative(@Param("email") String email);
    
    // Modifying query
    @Modifying
    @Query("UPDATE User u SET u.status = :status WHERE u.lastLogin < :date")
    int deactivateInactiveUsers(@Param("date") LocalDate date, 
                                 @Param("status") UserStatus status);
    
    // Projections
    interface UserProjection {
        String getName();
        String getEmail();
    }
    List<UserProjection> findAllProjectedBy();
}
```

### Locking Strategies

```java
// OPTIMISTIC LOCKING (default — @Version)
@Entity
public class Account {
    @Id
    private Long id;
    private BigDecimal balance;
    
    @Version
    private Long version;  // Incremented on each update
    
    // On concurrent update:
    // OptimisticLockException → retry
}

// PESSIMISTIC LOCKING
public interface AccountRepository extends JpaRepository<Account, Long> {
    
    @Lock(LockModeType.PESSIMISTIC_WRITE)  // SELECT ... FOR UPDATE
    @Query("SELECT a FROM Account a WHERE a.id = :id")
    Optional<Account> findByIdWithLock(@Param("id") Long id);
    
    @Lock(LockModeType.PESSIMISTIC_READ)   // SELECT ... FOR SHARE
    @Query("SELECT a FROM Account a WHERE a.id = :id")
    Optional<Account> findByIdWithSharedLock(@Param("id") Long id);
}
```

### Hibernate Common Pitfalls

```java
// ═══════════════════════════════════════════════════════════════
// PITFALL 1: LazyInitializationException
// ═══════════════════════════════════════════════════════════════
@Transactional(readOnly = true)
public Order getOrder(Long id) {
    Order order = orderRepository.findById(id).orElseThrow();
    // Transaction closes here → connection returned to pool
    return order;
}
// In controller:
// order.getItems().size();  // ← LazyInitializationException!
// Hibernate session is closed (transaction ended)

// Fix: JOIN FETCH in query, @EntityGraph, or Open Session in View
// But OSIV is an anti-pattern:
// spring.jpa.open-in-view=false  ← Disable (true by default in Spring Boot 2.x+)

// ═══════════════════════════════════════════════════════════════
// PITFALL 2: N+1 in serialization (Jackson)
// ═══════════════════════════════════════════════════════════════
@Entity
public class User {
    @OneToMany(mappedBy = "user", fetch = FetchType.LAZY)
    @JsonIgnore  // ← Critical: prevent Jackson from triggering lazy load
    private List<Order> orders;
    
    @JsonProperty("order_count")
    public int getOrderCount() {
        return orders.size();  // Still triggers N+1
    }
}
```

---

## 7. Spring Security Internals

### Security Filter Chain

```java
// Spring Security is implemented as a chain of servlet filters.
// The filter chain is ordered:

// 1. SecurityContextPersistenceFilter:
//    - Reads SecurityContext from HttpSession
//    - Stores it in SecurityContextHolder (ThreadLocal)
//    - After request: saves back to session, clears ThreadLocal

// 2. LogoutFilter:
//    - Checks if this is a logout request
//    - Invalidates session, clears context

// 3. UsernamePasswordAuthenticationFilter:
//    - Checks if this is a login request (/login POST)
//    - Extracts username + password
//    - Creates UsernamePasswordAuthenticationToken
//    - Delegates to AuthenticationManager
//    - On success: sets SecurityContext, redirects
//    - On failure: forwards to error page

// 4. ExceptionTranslationFilter:
//    - Catches AuthenticationException → 401 or redirect to login
//    - Catches AccessDeniedException → 403

// 5. FilterSecurityInterceptor:
//    - Last filter in chain
//    - Gets Authentication from SecurityContextHolder
//    - Checks if authenticated user has permission
//    - Uses AccessDecisionManager to vote
```

### Authentication Flow

```java
// 1. SecurityContextPersistenceFilter loads existing context
//    ← from session (form-login) or reconstructs from JWT

// 2. If no context, request passes through

// 3. If restricted URL:
//    FilterSecurityInterceptor.intercept() →
//    → AccessDecisionManager.decide()
//       → AccessDecisionVoter votes:
//          - RoleVoter: check GrantedAuthority
//          - AuthenticatedVoter: check auth level
//          - CustomVoter: your rules
//    → If DENIED → AccessDeniedException → ExceptionTranslationFilter → 403

// 4. AuthenticationManager delegates to ProviderManager:
//    → Try each AuthenticationProvider in order:
//       - DaoAuthenticationProvider: user details service + password encoder
//       - RememberMeAuthenticationProvider
//       - Custom provider
```

### Security Configuration (Java Config)

```java
@Configuration
@EnableWebSecurity
public class SecurityConfig {
    
    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/api/public/**").permitAll()
                .requestMatchers("/api/admin/**").hasRole("ADMIN")
                .requestMatchers("/api/user/**").hasAnyRole("USER", "ADMIN")
                .anyRequest().authenticated()
            )
            .oauth2ResourceServer(oauth2 -> oauth2
                .jwt(jwt -> jwt.jwtAuthenticationConverter(jwtConverter()))
            )
            .sessionManagement(session -> session
                .sessionCreationPolicy(SessionCreationPolicy.STATELESS)
            )
            .exceptionHandling(exc -> exc
                .authenticationEntryPoint((req, resp, auth) -> 
                    resp.sendError(HttpServletResponse.SC_UNAUTHORIZED))
                .accessDeniedHandler((req, resp, exc) -> 
                    resp.sendError(HttpServletResponse.SC_FORBIDDEN))
            );
        return http.build();
    }
    
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
    
    @Bean
    public JwtDecoder jwtDecoder() {
        // Configure JWT validation
        return NimbusJwtDecoder.withJwkSetUri("https://auth.example.com/.well-known/jwks.json")
            .build();
    }
}
```

---

## 8. Spring MVC — Request Processing

### Request Lifecycle

```
HTTP Request
    │
    ▼
Tomcat Connector (Acceptor thread → Socket → Worker thread)
    │
    ▼
ApplicationFilterChain (servlet filters)
    │  ├── CharacterEncodingFilter
    │  ├── HiddenHttpMethodFilter  
    │  ├── FormContentFilter
    │  ├── SecurityFilterChain (Spring Security)
    │  └── RequestContextFilter
    │
    ▼
DispatcherServlet (Front Controller)
    │
    ├── 1. MultipartResolver: check for file upload
    ├── 2. LocaleResolver: resolve request locale
    ├── 3. ThemeResolver: resolve theme
    │
    ├── 4. HandlerMapping: find controller for request
    │   ├── RequestMappingHandlerMapping: @RequestMapping
    │   └── SimpleUrlHandlerMapping: explicit URL mappings
    │
    ├── 5. HandlerAdapter: invoke controller
    │   ├── RequestMappingHandlerAdapter
    │   │   ├── Resolve method arguments (HandlerMethodArgumentResolver)
    │   │   │   ├── @RequestParam, @PathVariable, @RequestBody
    │   │   │   ├── @ModelAttribute, @SessionAttribute
    │   │   │   └── Custom resolvers
    │   │   ├── Invoke controller method
    │   │   └── Process return value (HandlerMethodReturnValueHandler)
    │   │       ├── @ResponseBody → HttpMessageConverter (Jackson)
    │   │       ├── ModelAndView → ViewResolver
    │   │       └── ResponseEntity → response + headers
    │   └── ...
    │
    ├── 6. ExceptionResolver: handle controller exceptions
    │   ├── ExceptionHandlerExceptionResolver: @ExceptionHandler
    │   ├── ResponseStatusExceptionResolver: @ResponseStatus
    │   └── DefaultHandlerExceptionResolver: Spring MVC exceptions
    │
    ├── 7. ViewResolver: resolve view name to View
    ├── 8. Interceptor.postHandle(): modify ModelAndView
    │   └── mvc:interceptors
    │
    └── 9. Interceptor.afterCompletion(): cleanup/logging
```

### HandlerMethodArgumentResolver — Custom

```java
@Component
public class CurrentUserArgumentResolver implements HandlerMethodArgumentResolver {
    
    @Override
    public boolean supportsParameter(MethodParameter parameter) {
        return parameter.hasParameterAnnotation(CurrentUser.class) 
            && parameter.getParameterType().equals(User.class);
    }
    
    @Override
    public Object resolveArgument(MethodParameter parameter,
                                    ModelAndViewContainer mavContainer,
                                    NativeWebRequest webRequest,
                                    WebsDataBinderFactory binderFactory) 
            throws Exception {
        // Extract user from security context or JWT
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !auth.isAuthenticated()) {
            return null;
        }
        return auth.getPrincipal();
    }
}

// Usage:
@GetMapping("/profile")
public UserProfile profile(@CurrentUser User user) {
    return userService.getProfile(user.getId());
}
```

---

## 9. Spring Boot Actuator & Observability

### Actuator Endpoints

```java
// Management endpoints (exposed via HTTP or JMX):
// /actuator/health        — Application health
// /actuator/info          — Application info
// /actuator/metrics       — Micrometer metrics
// /actuator/prometheus    — Prometheus scrape endpoint
// /actuator/env           — Environment properties (sensitive!)
// /actuator/configprops   — @ConfigurationProperties
// /actuator/beans         — All beans in context
// /actuator/loggers       — Log levels (can change at runtime!)
// /actuator/threaddump    — Thread dump
// /actuator/heapdump      — Heap dump (can be large)
// /actuator/httptrace     — HTTP request-response traces
// /actuator/auditevents   — Audit events
```

### Custom Health Indicator

```java
@Component
public class DatabaseHealthIndicator implements HealthIndicator {
    
    @Autowired
    private DataSource dataSource;
    
    @Override
    public Health health() {
        try (Connection conn = dataSource.getConnection()) {
            if (!conn.isValid(1)) {  // 1 second timeout
                return Health.down()
                    .withDetail("database", "Connection validation failed")
                    .build();
            }
            
            // Check replication lag
            try (Statement stmt = conn.createStatement()) {
                ResultSet rs = stmt.executeQuery("SHOW STATUS LIKE 'Seconds_Behind_Master'");
                if (rs.next()) {
                    int lag = rs.getInt("Value");
                    if (lag > 30) {
                        return Health.status("DEGRADED")
                            .withDetail("database", "Replication lag: " + lag + "s")
                            .build();
                    }
                }
            }
            
            return Health.up()
                .withDetail("database", "Available")
                .withDetail("maxConnections", 20)
                .build();
                
        } catch (Exception e) {
            return Health.down(e)
                .withDetail("database", e.getMessage())
                .build();
        }
    }
}
```

### Micrometer & Prometheus

```java
@RestController
public class MetricsController {
    
    private final MeterRegistry meterRegistry;
    private final Counter requestCounter;
    private final Timer requestTimer;
    
    public MetricsController(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
        this.requestCounter = Counter.builder("api.requests.total")
            .description("Total API requests")
            .register(meterRegistry);
        this.requestTimer = Timer.builder("api.requests.duration")
            .description("API request duration")
            .publishPercentiles(0.5, 0.95, 0.99)
            .register(meterRegistry);
    }
    
    @GetMapping("/api/items")
    public List<Item> getItems() {
        requestCounter.increment();
        return requestTimer.record(() -> itemService.findAll());
    }
}
```

---

## 10. Testing Strategies

### Unit Testing with Mockito

```java
@ExtendWith(MockitoExtension.class)
class UserServiceTest {
    
    @Mock
    private UserRepository userRepository;
    
    @Mock
    private EmailService emailService;
    
    @InjectMocks
    private UserService userService;  // Creates with injected mocks
    
    @Test
    void createUser_shouldSaveAndSendEmail() {
        // Given
        User user = new User("test@example.com", "Test");
        when(userRepository.save(any(User.class)))
            .thenReturn(user);
        
        // When
        User result = userService.createUser(user);
        
        // Then
        assertThat(result).isEqualTo(user);
        verify(userRepository).save(user);
        verify(emailService).sendWelcomeEmail("test@example.com");
    }
    
    @Test
    void createUser_duplicateEmail_shouldThrow() {
        // Given
        when(userRepository.findByEmail("existing@example.com"))
            .thenReturn(Optional.of(new User()));
        
        // When/Then
        assertThatThrownBy(() -> 
            userService.createUser(new User("existing@example.com", "Test"))
        ).isInstanceOf(DuplicateEmailException.class);
        
        verify(userRepository, never()).save(any());
    }
}
```

### Integration Testing

```java
@SpringBootTest(webEnvironment = WebEnvironment.RANDOM_PORT)
@AutoConfigureMockMvc
class UserControllerIntegrationTest {
    
    @Autowired
    private MockMvc mockMvc;
    
    @Autowired
    private UserRepository userRepository;
    
    @BeforeEach
    void setUp() {
        userRepository.deleteAll();
    }
    
    @Test
    void getUsers_shouldReturnList() throws Exception {
        // Given
        userRepository.save(new User("alice@example.com", "Alice"));
        userRepository.save(new User("bob@example.com", "Bob"));
        
        // When/Then
        mockMvc.perform(get("/api/users")
                .contentType(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(2))
            .andExpect(jsonPath("$[0].email").value("alice@example.com"));
    }
    
    @Test
    void createUser_shouldReturnCreated() throws Exception {
        mockMvc.perform(post("/api/users")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {"email": "new@example.com", "name": "New User"}
                    """))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.email").value("new@example.com"));
        
        assertThat(userRepository.findByEmail("new@example.com")).isPresent();
    }
}
```

### Database Testing with Testcontainers

```java
@Testcontainers
@SpringBootTest
class UserRepositoryTest {
    
    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine")
        .withDatabaseName("testdb")
        .withUsername("test")
        .withPassword("test");
    
    @DynamicPropertySource
    static void configureProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
    }
    
    @Autowired
    private UserRepository userRepository;
    
    @Test
    void findByEmail_shouldFind() {
        userRepository.save(new User("test@example.com", "Test"));
        
        Optional<User> found = userRepository.findByEmail("test@example.com");
        
        assertThat(found).isPresent();
        assertThat(found.get().getName()).isEqualTo("Test");
    }
}
```

---

## 11. Production Patterns & Pitfalls

### Graceful Shutdown

```java
@SpringBootApplication
public class Application {
    
    public static void main(String[] args) {
        SpringApplication app = new SpringApplication(Application.class);
        app.setDefaultProperties(Map.of(
            "server.shutdown", "graceful"      // Wait for active requests
        ));
        app.run(args);
    }
}

// Config:
// server.shutdown=graceful
// spring.lifecycle.timeout-per-shutdown-phase=30s
```

### Common Production Pitfalls

```java
// ═══════════════════════════════════════════════════════════════
// PITFALL 1: Component Scan on wrong package
// ═══════════════════════════════════════════════════════════════
@SpringBootApplication
@ComponentScan("com.otherpackage")  // ← Scans wrong package!
// Fix: @SpringBootApplication is already @ComponentScan for the current package
// Only use @ComponentScan if you need ADDITIONAL packages

// ═══════════════════════════════════════════════════════════════
// PITFALL 2: @Value without fallback
// ═══════════════════════════════════════════════════════════════
@Value("${myapp.api.key}")  // ← Fails to start if property missing!
private String apiKey;

// Fix: provide default
@Value("${myapp.api.key:default-key}")
private String apiKey;

// ═══════════════════════════════════════════════════════════════
// PITFALL 3: Transactional + async = lost transaction context
// ═══════════════════════════════════════════════════════════════
@Service
public class MyService {
    @Transactional
    @Async  // ← Transaction doesn't propagate to async thread!
    public void doWork() {
        // Transaction runs in a DIFFERENT thread
        // TransactionSynchronizationManager has NO transaction bound!
        userRepository.save(user);  // Runs WITHOUT transaction!
    }
    
    // Fix: move @Async to a separate method WITHOUT @Transactional
    @Async
    public void doWorkAsync(Long userId) {
        doWorkInTransaction(userId);  // Separate @Transactional call
    }
    
    @Transactional
    public void doWorkInTransaction(Long userId) {
        userRepository.save(new User(userId));
    }
}

// ═══════════════════════════════════════════════════════════════
// PITFALL 4: Open Session In View (OSIV) — performance killer
// ═══════════════════════════════════════════════════════════════
// OSIV (default: ON) keeps Hibernate session open during view rendering
// Problem:
// - Database connection held for entire request
// - Pool exhaustion under high load
// - Lazy loading hides N+1 queries
// 
// Fix: spring.jpa.open-in-view=false
// Then ensure all data is fetched in the service layer

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
        Product product = getProduct(id);  // ← Cache MISSED!
        // "this" is the real bean, not the proxy
        // @Cacheable AOP doesn't apply!
        
        // Fix: self-inject or use CacheManager directly
        return applyDiscount(product);
    }
}
```

---

## 12. Spring Boot Interview Questions

### Beginner

<details>
<summary><b>Q1: What is Dependency Injection? Why does Spring prefer constructor injection?</b></summary>

**Answer:** Dependency Injection is a pattern where objects receive their dependencies from an external source rather than creating them internally. Spring prefers constructor injection because:
1. **Immutability**: Dependencies can be final (assigned once in constructor)
2. **Testability**: Objects can be constructed with mocks easily
3. **Null safety**: Constructor fails at build time if dependencies missing
4. **Circular dependency detection**: Detected at startup, not runtime
5. **Explicit dependencies**: Clear what the class needs
</details>

<details>
<summary><b>Q2: What is the difference between @Component, @Service, @Repository, and @Controller?</b></summary>

**Answer:** They are all specializations of @Component:
- **@Component**: Generic stereotype for any Spring-managed bean
- **@Service**: Business logic layer (service classes)
- **@Repository**: Data access layer (DAO/Repository). Adds:
  - Automatic exception translation (SQLException → DataAccessException)
  - Component scanning optimization
- **@Controller**: Web layer (MVC controllers). Adds:
  - Handler mapping detection
  - View resolution support

All enable component scanning and serve as type-level filters for AOP.
</details>

<details>
<summary><b>Q3: What is Spring Boot auto-configuration?</b></summary>

**Answer:** Auto-configuration is Spring Boot's way of automatically configuring beans based on:
1. **Classpath dependencies**: If H2 is on classpath → configure DataSource
2. **Existing beans**: If user defined DataSource → don't create another
3. **Properties**: Customize via application.properties/yml
4. **Conditions**: @ConditionalOnClass, @ConditionalOnMissingBean, etc.

Auto-configuration classes are loaded from `META-INF/spring/AutoConfiguration.imports` and evaluated in order. Users can exclude specific auto-configurations via `@SpringBootApplication(exclude = ...)`.
</details>

### Intermediate

<details>
<summary><b>Q4: How does Spring resolve circular dependencies?</b></summary>

**Answer:** Spring uses a **three-level cache** (singletonFactories → earlySingletonObjects → singletonObjects):

1. **Level 3** (`singletonFactories`): Stores an `ObjectFactory` for each bean being created. Before populating dependencies, the raw bean is wrapped in an ObjectFactory and stored here.

2. **Level 2** (`earlySingletonObjects`): If a circular reference is detected (bean A needs B, B needs A), the raw A from Level 3 is moved to Level 2 (early exposure).

3. **Level 1** (`singletonObjects`): Fully initialized beans (after post-processing).

**Limitation**: Constructor injection does NOT support circular dependencies because the raw bean isn't available yet when constructor arguments need to be resolved.
</details>

<details>
<summary><b>Q5: What is the difference between JDK Dynamic Proxy and CGLIB Proxy?</b></summary>

**Answer:** 
- **JDK Proxy**: Creates proxy at interface level. Only intercepts methods declared in the bean's interfaces. Uses Java's `java.lang.reflect.Proxy` and `InvocationHandler`. Default when bean implements at least one interface.
- **CGLIB Proxy**: Creates proxy by subclassing the bean class. Can intercept all non-final methods (including non-interface methods). Uses bytecode generation (or ByteBuddy in Spring Boot 3+). Enabled via `spring.aop.proxy-target-class=true` (default in Spring Boot).

JDK proxy is slightly faster but limits AOP to interface methods. CGLIB can proxy concrete classes but can't intercept final methods.
</details>

<details>
<summary><b>Q6: How does @Transactional work with AOP?</b></summary>

**Answer:** `@Transactional` is implemented via AOP:

1. `BeanPostProcessor` (specifically `BeanFactoryTransactionAttributeSourceAdvisor`) detects beans with `@Transactional` methods
2. Creates an AOP proxy around the bean
3. When a transactional method is called through the proxy, `TransactionInterceptor` runs:
   - Checks propagation level and existing transaction
   - Creates/suspends/joins transaction
   - Invokes the actual method (via `invocation.proceed()`)
   - On success: commit
   - On exception: rollback (if RuntimeException)
4. The transaction context is stored in `ThreadLocal` via `TransactionSynchronizationManager`

**Critical**: The proxy only intercepts external calls. Self-invocation bypasses the proxy → no transaction!
</details>

### Advanced

<details>
<summary><b>Q7: What happens on Spring Boot startup when `@SpringBootApplication` is encountered?</b></summary>

**Answer:** The `SpringApplication.run()` call triggers:

1. **SpringApplication initializes**: Determines web application type, loads initializers and listeners
2. **Environment prepared**: Loads application.properties/yml, command-line args, profiles
3. **Banner printed** (optional)
4. **ApplicationContext created**: `AnnotationConfigServletWebServerApplicationContext`
5. **prepareContext**: Set environment, post-process, initialize sources
6. **refreshContext**: Calls `AbstractApplicationContext.refresh()` which:
   - Creates and configures BeanFactory
   - Invokes BeanFactoryPostProcessors (config classes, property sources)
   - Registers BeanPostProcessors
   - Initializes message source, event multicaster
   - **onRefresh()** → creates embedded Tomcat/Jetty/Undertow server
   - Registers listeners
   - **Finishes initialization**: Creates all singleton beans, publishes ContextRefreshedEvent
7. **afterRefresh**: Runner's `ApplicationRunner` and `CommandLineRunner` beans execute
8. **ApplicationReadyEvent** published, application is ready
</details>

<details>
<summary><b>Q8: Design a multi-tenant SaaS application with Spring Boot. How do you isolate tenant data?</b></summary>

**Answer:** Three strategies:

1. **Schema-per-tenant** (single database, separate schemas):
```java
// Dynamic DataSource routing
@Component
public class TenantAwareDataSourceRouter extends AbstractRoutingDataSource {
    @Override
    protected Object determineCurrentLookupKey() {
        return TenantContext.getCurrentTenant();  // ThreadLocal
    }
}
// Pros: Strong isolation, easy to restore
// Cons: Connection pool per schema, schema migration complexity
```

2. **Database-per-tenant** (separate databases):
```java
// Map of DataSources, one per tenant
@Component
public class MultiTenantDataSource {
    private final Map<String, DataSource> datasources = new ConcurrentHashMap<>();
    
    public DataSource resolve(String tenantId) {
        return datasources.computeIfAbsent(tenantId, this::createDataSource);
    }
}
// Pros: Maximum isolation, per-tenant scaling
// Cons: Connection overhead, centralized management
```

3. **Row-level isolation** (shared table, tenant_id column):
```java
@Entity
@Where(clause = "tenant_id = :tenantId")  // Hibernate filter
public class Order {
    private String tenantId;  // Set automatically
}
// Pros: Simple, efficient queries
// Cons: Weaker isolation, query complexity
```

Most SaaS apps start with row-level and move to schema-per-tenant as they grow.
</details>

<details>
<summary><b>Q9: How would you optimize a Spring Boot application that's too slow to start?</summary>

**Answer:**
1. **Lazy initialization**: `spring.main.lazy-initialization=true` (Spring Boot 2.2+)
2. **Exclude unnecessary auto-configuration**: Remove unused starters
3. **Component scan optimization**: Use specific packages, not base packages
4. **Disable unused features**: JMX (`spring.jmx.enabled=false`), unused actuators
5. **Minimize embedded container features**: `server.tomcat.accesslog.enabled=false`
6. **Use Spring AOT (GraalVM native)**: Ahead-of-time compilation (Spring Boot 3+)
7. **Check for slow BeanPostProcessors**: Custom post-processors can add to startup
8. **Use context indexer**: `spring-context-indexer` annotation processor (caches component scan)
9. **Profile-specific configuration**: Lightweight profile for development
10. **Parallel bean initialization**: `spring.main.allow-bean-definition-overriding=false`

Typical time distribution: 40% component scan, 30% bean creation, 20% auto-config evaluation, 10% other
</details>

<details>
<summary><b>Q10: Design a rate-limiting system for a Spring Boot REST API. Could you implement it as a custom filter or interceptor?</summary>

**Answer:**
```java
@Component
public class RateLimitingInterceptor implements HandlerInterceptor {
    
    private final RateLimiter rateLimiter;
    
    public RateLimitingInterceptor(RateLimiter rateLimiter) {
        this.rateLimiter = rateLimiter;
    }
    
    @Override
    public boolean preHandle(HttpServletRequest request, 
                              HttpServletResponse response, 
                              Object handler) throws Exception {
        String clientId = resolveClientId(request);
        String endpoint = request.getRequestURI();
        
        if (!rateLimiter.allowRequest(clientId, endpoint)) {
            response.setStatus(429);
            response.setContentType("application/json");
            response.getWriter().write("""
                {"error": "Rate limit exceeded", "retryAfter": "%ds"}
                """.formatted(rateLimiter.getRetryAfter(clientId, endpoint)));
            return false;
        }
        
        response.addHeader("X-RateLimit-Remaining", 
            String.valueOf(rateLimiter.getRemaining(clientId, endpoint)));
        return true;
    }
    
    private String resolveClientId(HttpServletRequest request) {
        // API key, user ID, or IP address
        String apiKey = request.getHeader("X-API-Key");
        if (apiKey != null) return apiKey;
        
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.isAuthenticated()) {
            return auth.getName();
        }
        
        return request.getRemoteAddr();
    }
}

// Register:
@Configuration
public class WebConfig implements WebMvcConfigurer {
    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new RateLimitingInterceptor(rateLimiter))
            .addPathPatterns("/api/**")
            .excludePathPatterns("/api/public/**");
    }
}

// Implementation (sliding window log with Redis):
@Component
public class SlidingWindowRateLimiter {
    private final RedisTemplate<String, String> redis;
    
    public boolean allowRequest(String clientId, String endpoint, 
                                  int maxRequests, int windowSeconds) {
        String key = "ratelimit:" + clientId + ":" + endpoint;
        long now = System.currentTimeMillis();
        long windowStart = now - (windowSeconds * 1000L);
        
        // Remove old entries
        redis.opsForZSet().removeRangeByScore(key, 0, windowStart);
        
        // Count current entries
        Long count = redis.opsForZSet().size(key);
        
        if (count != null && count >= maxRequests) {
            return false;
        }
        
        // Add current request
        redis.opsForZSet().add(key, String.valueOf(now), now);
        redis.expire(key, Duration.ofSeconds(windowSeconds * 2));
        
        return true;
    }
}
```
</details>

---

## Quick Reference: Spring Boot at a Glance

| Concept | Key Point |
|---------|-----------|
| **IoC Container** | ApplicationContext manages beans via DI |
| **Bean Lifecycle** | 11 steps: instantiate → populate → aware → pre-init → init → post-init |
| **Auto-Configuration** | Conditions + AutoConfiguration.imports |
| **AOP Proxy** | JDK (interface) or CGLIB (subclass) — wraps beans for aspects |
| **@Transactional** | Propagation (REQUIRED, REQUIRES_NEW), Isolation (READ_COMMITTED) |
| **Self-invocation** | AOP/transaction broken when `this.method()` called from inside bean |
| **OSIV** | Anti-pattern: session held for entire request |
| **Structured Logging** | Use MDC for request-scoped context |
| **Observability** | Micrometer → Prometheus → Grafana |
| **Testing** | Mockito (unit) + Testcontainers (integration) |

---

> *Use these notes as a comprehensive reference for Spring Boot internals. Staff/Principal interviews focus on understanding WHY Spring works the way it does — with deep knowledge of proxies, transactions, auto-configuration, and production patterns.*
